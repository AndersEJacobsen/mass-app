package io.music_assistant.client.ui.compose.home.players

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * A chapter's fractional start must round UP to whole seconds, so an
 * integer-second seek lands inside the tapped chapter — never a fraction of a
 * second before it, which would briefly highlight the previous chapter.
 */
class ChapterSeekSecondsTest {
    @Test
    fun wholeSecondStartIsUnchanged() {
        assertEquals(100L, chapterSeekSeconds(100.0))
    }

    @Test
    fun fractionJustPastBoundaryRoundsUp() {
        assertEquals(101L, chapterSeekSeconds(100.1))
    }

    @Test
    fun fractionNearNextBoundaryRoundsUp() {
        assertEquals(101L, chapterSeekSeconds(100.9))
    }

    @Test
    fun zeroStartStaysZero() {
        assertEquals(0L, chapterSeekSeconds(0.0))
    }
}
