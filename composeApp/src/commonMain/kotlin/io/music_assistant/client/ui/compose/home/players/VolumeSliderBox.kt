package io.music_assistant.client.ui.compose.home.players

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToUp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.unit.dp
import kotlin.math.abs

/**
 * Wraps a volume [slider] with a tap-to-step gesture: a tap on the left half steps
 * the volume down, a tap on the right half steps it up. Taps on/near the thumb and
 * drags are handed off to the slider so normal dragging still works.
 *
 * The single source of truth for the expanded-player and group-settings volume
 * controls — keep the action mapping (down/up vs. group down/up) at the call site.
 */
@Composable
fun VolumeSliderBox(
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    volume: () -> Float,
    onStepDown: () -> Unit,
    onStepUp: () -> Unit,
    slider: @Composable () -> Unit,
) {
    val touchSlopPx = LocalViewConfiguration.current.touchSlop
    val thumbHitPx = with(LocalDensity.current) { 24.dp.toPx() }
    val volumeForGesture by rememberUpdatedState(volume())
    val gesture = if (enabled) {
        Modifier.pointerInput(Unit) {
            awaitEachGesture {
                val widthPx = size.width
                if (widthPx == 0) return@awaitEachGesture
                val down = awaitFirstDown(
                    requireUnconsumed = false,
                    pass = PointerEventPass.Initial,
                )
                val thumbCenter = (volumeForGesture / 100f) * widthPx
                // Tap on/near thumb: hand off to the Slider so dragging works normally.
                if (abs(down.position.x - thumbCenter) <= thumbHitPx) {
                    return@awaitEachGesture
                }
                down.consume()
                var dragged = false
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    val change = event.changes
                        .firstOrNull { it.id == down.id } ?: break
                    if (!dragged &&
                        (change.position - down.position).getDistance() > touchSlopPx
                    ) {
                        dragged = true
                    }
                    if (change.changedToUp()) {
                        change.consume()
                        if (!dragged) {
                            if (down.position.x < widthPx / 2f) onStepDown() else onStepUp()
                        }
                        break
                    } else {
                        change.consume()
                    }
                }
            }
        }
    } else {
        Modifier
    }
    Box(modifier = modifier.then(gesture)) {
        slider()
    }
}
