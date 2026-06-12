package io.music_assistant.client.api

import co.touchlab.kermit.Logger
import kotlinx.atomicfu.locks.SynchronizedObject
import kotlinx.atomicfu.locks.synchronized
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/**
 * Handles RPC request/response correlation for the Music Assistant API.
 *
 * Manages pending request callbacks and partial result accumulation. The
 * server sends large result sets in 500-item batches with `"partial": true`;
 * this class accumulates them and delivers the merged result to the caller.
 *
 * Thread-safety: [registerCallback] and [removeCallback] are called from
 * request-issuing coroutines on `Dispatchers.IO`, while [handleResponse]
 * runs on the websocket message-collector coroutine. On Kotlin/Native those
 * can run on different threads, and [kotlin.collections.HashMap] is not
 * concurrency-safe — concurrent mutations corrupt its internal buckets and
 * surface as `ArrayIndexOutOfBoundsException` out of `HashMap#addKey`. We
 * guard the pending-callback and partial-result maps with one common lock
 * so related state transitions (e.g. cancel vs. late partial response)
 * cannot leave orphaned partial batches behind.
 *
 * @param onAuthError Called when the server returns `error_code 20`
 *   (token expired/invalid).
 * @param onError Called with the server-supplied `details` string for any
 *   other RPC error, so the app can surface it to the user.
 */
class RpcEngine(
    private val onAuthError: () -> Unit,
    private val onError: (String) -> Unit,
) {
    private val logger = Logger.withTag("RpcEngine")

    private val lock = SynchronizedObject()
    private val pendingResponses = mutableMapOf<String, (Result<Answer>) -> Unit>()

    // Accumulated partial results: message_id -> list of result items received so far.
    private val partialResults = mutableMapOf<String, List<JsonElement>>()

    /**
     * Handle an incoming message. Returns true if the message was an RPC
     * response (has `message_id`), false if the caller should process it as
     * an event or other message.
     */
    fun handleResponse(message: JsonObject): Boolean {
        val messageId = message["message_id"]?.jsonPrimitive?.contentOrNull ?: return false
        val isPartial = message["partial"]?.jsonPrimitive?.boolean == true

        if (isPartial) {
            val resultArray = message["result"]?.jsonArray
            if (resultArray == null || resultArray.isEmpty()) return true
            synchronized(lock) {
                // Check and write under the same lock. If cancellation/final response
                // already removed the callback, no late partial can be orphaned.
                if (!pendingResponses.containsKey(messageId)) return@synchronized
                val existing = partialResults[messageId].orEmpty()
                partialResults[messageId] = existing + resultArray
            }
            return true
        }

        // Final response — atomically remove the callback and drain partials.
        val callbackAndAnswer = synchronized(lock) {
            val callback = pendingResponses.remove(messageId) ?: return@synchronized null
            val accumulated = partialResults.remove(messageId)

            val finalMessage = if (accumulated != null) {
                val merged = accumulated.toMutableList()
                message["result"]?.jsonArray?.let(merged::addAll)
                JsonObject(message.toMutableMap().apply { put("result", JsonArray(merged)) })
            } else {
                message
            }

            callback to Answer(finalMessage)
        } ?: return true

        val (callback, answer) = callbackAndAnswer
        if (answer.json.containsKey("error_code")) {
            logger.e { "RPC error for message $messageId: $answer" }
            val errorCode = answer.json["error_code"]?.jsonPrimitive?.int
            if (errorCode == ERROR_CODE_AUTH_REQUIRED) {
                onAuthError()
            } else {
                answer.json["details"]?.jsonPrimitive?.contentOrNull
                    ?.takeIf { it.isNotBlank() }
                    ?.let(onError)
            }
        }
        callback.invoke(Result.success(answer))
        return true
    }

    /** Register a pending request callback by message_id. */
    fun registerCallback(messageId: String, callback: (Result<Answer>) -> Unit) {
        synchronized(lock) { pendingResponses[messageId] = callback }
    }

    /** Remove a pending request callback (for cancellation on send failure). */
    fun removeCallback(messageId: String) {
        synchronized(lock) {
            pendingResponses.remove(messageId)
            // Drop any partials accumulated for a request that will never resolve.
            partialResults.remove(messageId)
        }
    }

    /**
     * Atomically remove and return a pending callback. The removal is the
     * single-resume arbiter: of the racing paths (response, send failure,
     * [failAllPending]), only the one that wins it may resume the caller.
     */
    fun takeCallback(messageId: String): ((Result<Answer>) -> Unit)? =
        synchronized(lock) {
            partialResults.remove(messageId)
            pendingResponses.remove(messageId)
        }

    /**
     * Fail every pending request with [cause]. Call whenever the transport can no
     * longer deliver responses: callers suspend until resumed, so dropping the
     * callbacks instead would hang them for the session.
     */
    fun failAllPending(cause: Throwable) {
        val callbacks = synchronized(lock) {
            val callbacks = pendingResponses.values.toList()
            pendingResponses.clear()
            partialResults.clear()
            callbacks
        }
        if (callbacks.isEmpty()) return
        logger.i { "Failing ${callbacks.size} pending request(s): ${cause.message}" }
        callbacks.forEach { it.invoke(Result.failure(cause)) }
    }

    /** Cancel all pending requests — call on disconnect to prevent leaks. */
    fun clear() {
        failAllPending(IllegalStateException("Connection closed"))
    }

    private companion object {
        // Server emits this error_code when the session needs to re-auth (token expired, etc.).
        const val ERROR_CODE_AUTH_REQUIRED = 20
    }
}
