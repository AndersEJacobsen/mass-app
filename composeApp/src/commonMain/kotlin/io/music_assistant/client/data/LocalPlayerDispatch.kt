package io.music_assistant.client.data

import io.music_assistant.client.api.Request
import io.music_assistant.client.api.ServiceClient
import io.music_assistant.client.data.model.client.QueueOption

/**
 * Forces playback onto a specific player, mandatorily detaching it from
 * any sync group first. For surfaces where mirroring to other players
 * cannot be the user's intent: they're holding (or sitting in) the device
 * the audio has to come out of.
 */

internal data class LocalPlayerDispatchPlan(
    val playerId: String,
    val mediaUri: String,
    val detachFrom: String?,
    val option: QueueOption,
)

/** Returns null when prerequisites (a local player, a media URI) are missing. */
internal fun planLocalPlayerDispatch(
    localPlayerId: String?,
    localPlayerSyncedTo: String?,
    mediaUri: String?,
    option: QueueOption,
): LocalPlayerDispatchPlan? {
    if (localPlayerId == null || mediaUri == null) return null
    return LocalPlayerDispatchPlan(
        playerId = localPlayerId,
        mediaUri = mediaUri,
        detachFrom = localPlayerSyncedTo,
        option = option,
    )
}

/**
 * Detach must land before play — MA otherwise promotes
 * `play(queueOrPlayerId=childId)` to the group queue. Failures go through
 * [onRpcFailure] rather than try/catch: `sendRequest` is contractually
 * no-throw, and a catch-all would only break structured concurrency.
 */
internal suspend fun executeLocalPlayerDispatch(
    serviceClient: ServiceClient,
    plan: LocalPlayerDispatchPlan,
    onRpcFailure: (label: String, error: Throwable) -> Unit = { _, _ -> },
) {
    plan.detachFrom?.let { syncedToId ->
        serviceClient.sendRequest(
            Request.Player.setGroupMembers(
                playerId = syncedToId,
                playersToAdd = null,
                playersToRemove = listOf(plan.playerId),
            ),
        ).onFailure { onRpcFailure("detach", it) }
    }
    serviceClient.sendRequest(
        Request.Library.play(
            media = listOf(plan.mediaUri),
            queueOrPlayerId = plan.playerId,
            option = plan.option,
            radioMode = false,
        ),
    ).onFailure { onRpcFailure("play(${plan.option})", it) }
}
