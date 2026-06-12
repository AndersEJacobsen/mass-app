package io.music_assistant.client.data

import io.music_assistant.client.data.model.client.RepeatMode
import io.music_assistant.client.ui.compose.common.action.PlayerAction
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Locks the per-action classification: a wrong flip re-enables double-apply on
 * reconnect, and no other test would catch it. Constructor payloads are irrelevant
 * — replay-safety is a property of the command kind, not its value.
 */
class PlayerActionReplaySafetyTest {
    @Test
    fun relativeAndToggleCommandsAreNotReplaySafe() {
        listOf(
            PlayerAction.TogglePlayPause,
            PlayerAction.Next,
            PlayerAction.Previous,
            PlayerAction.VolumeUp,
            PlayerAction.VolumeDown,
            PlayerAction.GroupVolumeUp,
            PlayerAction.GroupVolumeDown,
            PlayerAction.SeekBy(offsetSeconds = 30),
        ).forEach { action ->
            assertFalse(action.isReplaySafe, "$action is relative; replay would double-apply")
        }
    }

    @Test
    fun absoluteAndIdempotentCommandsAreReplaySafe() {
        listOf(
            PlayerAction.Play,
            PlayerAction.Pause,
            PlayerAction.SeekTo(position = 0),
            PlayerAction.VolumeSet(level = 0.5),
            PlayerAction.ToggleMute(isMutedNow = false),
            PlayerAction.GroupVolumeSet(level = 0.5),
            PlayerAction.GroupToggleMute(isMutedNow = false),
            PlayerAction.GroupManage(),
            PlayerAction.ToggleShuffle(current = false),
            PlayerAction.ToggleRepeatMode(current = RepeatMode.OFF),
            PlayerAction.ToggleDontStopTheMusic(current = false),
            PlayerAction.SetPlaybackSpeed(speed = 1.0),
        ).forEach { action ->
            assertTrue(action.isReplaySafe, "$action is idempotent; it must still queue for replay")
        }
    }
}
