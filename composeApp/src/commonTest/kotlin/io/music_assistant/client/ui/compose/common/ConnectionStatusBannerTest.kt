package io.music_assistant.client.ui.compose.common

import io.music_assistant.client.api.ConnectionInfo
import io.music_assistant.client.utils.SessionState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ConnectionStatusBannerTest {
    private val connectionInfo = ConnectionInfo(host = "localhost", port = PORT, isTls = false)
    private val reconnecting =
        SessionState.Reconnecting.Direct(attempt = RECONNECT_ATTEMPT, connectionInfo = connectionInfo)

    @Test
    fun `reconnecting while online shows the reconnecting banner carrying its attempt`() {
        assertEquals(
            BannerState.Reconnecting(RECONNECT_ATTEMPT),
            reconnectionBannerState(reconnecting, isOnline = true),
        )
    }

    @Test
    fun `reconnecting while offline shows the no network banner`() {
        assertEquals(
            BannerState.NoNetwork,
            reconnectionBannerState(reconnecting, isOnline = false),
        )
    }

    @Test
    fun `offline while not reconnecting shows no banner`() {
        val connected = SessionState.Connected.Direct(connectionInfo)
        assertNull(reconnectionBannerState(connected, isOnline = false))
    }

    @Test
    fun `online while not reconnecting shows no banner`() {
        assertNull(reconnectionBannerState(SessionState.Disconnected.Initial, isOnline = true))
    }

    private companion object {
        const val RECONNECT_ATTEMPT = 3
        const val PORT = 8095
    }
}
