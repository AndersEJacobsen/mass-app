package io.music_assistant.client.logging

import kotlinx.atomicfu.locks.SynchronizedObject
import kotlinx.atomicfu.locks.synchronized

/**
 * Fixed-capacity, thread-safe buffer of recent log lines. Once full, [add] evicts
 * the oldest. The lock is non-suspend because Kermit's [co.touchlab.kermit.LogWriter.log]
 * is synchronous, ruling out a coroutines [kotlinx.coroutines.sync.Mutex].
 */
class LogRingBuffer(private val capacity: Int) {
    init {
        require(capacity > 0) { "capacity must be positive, was $capacity" }
    }

    private val lock = SynchronizedObject()
    private val entries = ArrayDeque<String>(capacity)

    fun add(line: String) = synchronized(lock) {
        if (entries.size == capacity) entries.removeFirst()
        entries.addLast(line)
    }

    fun snapshot(): List<String> = synchronized(lock) { entries.toList() }
}
