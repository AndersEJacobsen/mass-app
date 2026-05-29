package io.music_assistant.client.logging

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class LogRingBufferTest {
    @Test
    fun `snapshot returns all lines in insertion order when below capacity`() {
        val buffer = LogRingBuffer(capacity = 4)
        val lines = listOf("a", "b", "c")
        lines.forEach(buffer::add)
        assertEquals(lines, buffer.snapshot())
    }

    @Test
    fun `snapshot returns all lines when exactly at capacity`() {
        val capacity = 4
        val buffer = LogRingBuffer(capacity)
        val lines = List(capacity) { "line-$it" }
        lines.forEach(buffer::add)
        assertEquals(lines, buffer.snapshot())
    }

    @Test
    fun `snapshot keeps the most recent lines and evicts oldest when over capacity`() {
        val capacity = 4
        val buffer = LogRingBuffer(capacity)
        val lines = List(capacity * 2 + 1) { "line-$it" }
        lines.forEach(buffer::add)
        assertEquals(lines.takeLast(capacity), buffer.snapshot())
    }

    @Test
    fun `capacity of one retains only the last line`() {
        val buffer = LogRingBuffer(capacity = 1)
        listOf("first", "second", "third").forEach(buffer::add)
        assertEquals(listOf("third"), buffer.snapshot())
    }

    @Test
    fun `constructor rejects non-positive capacity`() {
        assertFailsWith<IllegalArgumentException> { LogRingBuffer(capacity = 0) }
        assertFailsWith<IllegalArgumentException> { LogRingBuffer(capacity = -1) }
    }
}
