"""Compiled, bounded file-name masks plus the existing substring search."""
from functools import lru_cache
from .file_masks import compile_file_mask


@lru_cache(maxsize=128)
def compile_file_filter(query):
    query = str(query or '').strip().casefold()
    if not query:
        return lambda item: True
    if not any(character in query for character in '*?[;,|<>'):
        def contains(item):
            return (query in item.cached_name_sort or query in item.cached_type_sort or
                    query in str(item.path or '').casefold())
        return contains
    return compile_file_mask(query)
