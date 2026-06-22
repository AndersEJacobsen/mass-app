package io.music_assistant.client.ui.compose.library

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.music_assistant.client.data.model.client.GenreEmptyFilter
import io.music_assistant.client.data.model.client.MediaType
import io.music_assistant.client.data.model.client.stringResource
import musicassistantclient.composeapp.generated.resources.Res
import musicassistantclient.composeapp.generated.resources.genre_filter_empty_all
import musicassistantclient.composeapp.generated.resources.genre_filter_empty_default
import musicassistantclient.composeapp.generated.resources.genre_filter_empty_non_empty
import musicassistantclient.composeapp.generated.resources.genre_filter_media_type
import musicassistantclient.composeapp.generated.resources.genre_filter_media_type_all
import musicassistantclient.composeapp.generated.resources.genre_filter_show
import org.jetbrains.compose.resources.StringResource
import org.jetbrains.compose.resources.stringResource

/**
 * Genres-only filter surface: a tri-state "show genres" choice and a single
 * media-type choice, in a dropdown anchored to the filter button. Selections
 * are written straight through to the VM (which persists them); picking any
 * option dismisses the menu.
 */
@Composable
fun GenreFilterMenu(
    expanded: Boolean,
    emptyFilter: GenreEmptyFilter,
    mediaTypeFilter: MediaType?,
    onEmptyFilterChange: (GenreEmptyFilter) -> Unit,
    onMediaTypeFilterChange: (MediaType?) -> Unit,
    onDismiss: () -> Unit,
) {
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        SectionHeader(Res.string.genre_filter_show)
        GenreEmptyFilter.entries.forEach { option ->
            FilterItem(
                label = stringResource(option.label()),
                selected = option == emptyFilter,
                onClick = {
                    onDismiss()
                    onEmptyFilterChange(option)
                },
            )
        }

        HorizontalDivider()

        SectionHeader(Res.string.genre_filter_media_type)
        FilterItem(
            label = stringResource(Res.string.genre_filter_media_type_all),
            selected = mediaTypeFilter == null,
            onClick = {
                onDismiss()
                onMediaTypeFilterChange(null)
            },
        )
        MediaType.genreMediaTypeOptions.forEach { type ->
            FilterItem(
                label = stringResource(type.stringResource()),
                selected = type == mediaTypeFilter,
                onClick = {
                    onDismiss()
                    onMediaTypeFilterChange(type)
                },
            )
        }
    }
}

@Composable
private fun SectionHeader(text: StringResource) {
    Text(
        text = stringResource(text),
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

@Composable
private fun FilterItem(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    DropdownMenuItem(
        text = { Text(label) },
        onClick = onClick,
        trailingIcon = if (selected) {
            {
                Icon(
                    Icons.Default.Check,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
            }
        } else {
            null
        },
    )
}

private fun GenreEmptyFilter.label(): StringResource = when (this) {
    GenreEmptyFilter.DEFAULT -> Res.string.genre_filter_empty_default
    GenreEmptyFilter.NON_EMPTY -> Res.string.genre_filter_empty_non_empty
    GenreEmptyFilter.ALL -> Res.string.genre_filter_empty_all
}
