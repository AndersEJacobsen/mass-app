package io.music_assistant.client.data.model.client

/**
 * Tri-state filter for the genres library list, mapped onto the server's
 * nullable `hide_empty` arg:
 *  - [DEFAULT]   → null  → server default (only "default" genres)
 *  - [NON_EMPTY] → true  → only genres that contain items
 *  - [ALL]       → false → every genre
 */
enum class GenreEmptyFilter(val hideEmpty: Boolean?) {
    DEFAULT(null),
    NON_EMPTY(true),
    ALL(false),
}
