package io.music_assistant.client.di

import co.touchlab.kermit.Logger
import co.touchlab.kermit.Severity
import coil3.SingletonImageLoader
import io.music_assistant.client.api.ServiceClient
import io.music_assistant.client.imageloader.WebRTCImageFetcher
import io.music_assistant.client.imageloader.buildAppImageLoader
import io.music_assistant.client.logging.InMemoryLogWriter
import org.koin.core.context.startKoin
import org.koin.core.module.Module
import org.koin.dsl.KoinAppDeclaration
import org.koin.mp.KoinPlatform

fun initKoin(
    vararg platformModules: Module,
    verboseLogging: Boolean = false,
    config: KoinAppDeclaration? = null,
) {
    // Release builds drop Debug/Verbose logs: the WebSocket layer emits ~4 debug
    // lines/sec for the idle clock-sync heartbeat, which otherwise floods (and
    // evicts useful entries from) InMemoryLogWriter for the entire session.
    Logger.setMinSeverity(if (verboseLogging) Severity.Verbose else Severity.Info)
    Logger.addLogWriter(InMemoryLogWriter)
    startKoin {
        config?.invoke(this)
        modules(sharedModule(), webrtcModule, *platformModules)
    }
    val webrtcFetcherFactory = WebRTCImageFetcher.Factory(KoinPlatform.getKoin().get<ServiceClient>())
    SingletonImageLoader.setSafe { context -> buildAppImageLoader(context, webrtcFetcherFactory) }
}
