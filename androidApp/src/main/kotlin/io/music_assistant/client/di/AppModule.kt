package io.music_assistant.client.di

import io.music_assistant.client.auto.AutoLibrary
import org.koin.android.ext.koin.androidContext
import org.koin.dsl.module

fun appModule() = module {
    single { AutoLibrary(androidContext(), get()) }
}
