{% macro normalize_name(column) %}
    {#
      Lowercase, remove apostrophes, turn '&' into 'and', strip punctuation,
      remove legal/taxonomy tokens, collapse whitespace.

      Apostrophes are deleted rather than replaced with a space so that
      "McDonald's" and "McDonalds" normalize to the same token. Hyphens become
      spaces, which matches "Baskin-Robbins" to "Baskin Robbins".
    #}
    nullif(
        trim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(lower({{ column }}), '[''’]', '', 'g'),
                            '&',
                            ' and ',
                            'g'
                        ),
                        '[^a-z0-9]+',
                        ' ',
                        'g'
                    ),
                    '\m(restaurant|the|llc|inc|cafe)\M',
                    ' ',
                    'g'
                ),
                '\s+',
                ' ',
                'g'
            )
        ),
        ''
    )
{% endmacro %}
