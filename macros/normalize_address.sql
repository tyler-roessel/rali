{% macro normalize_address(housenumber, street, city, postcode) %}
    {#
      Build a normalized address from the parts we actually have. House number
      and street are required: a city or postcode alone is not an address key.
      Unit/suite designators are removed before punctuation is collapsed.

      Replacements run inside-out: apostrophes, ampersand, unit designators,
      standalone #, punctuation, street suffix, directional prefix, whitespace.
    #}
    {% set raw_address = "concat_ws(' ', " ~ housenumber ~ ", " ~ street ~ ", " ~ city ~ ", " ~ postcode ~ ")" %}
    case
        when nullif(trim(concat_ws(' ', {{ housenumber }}, {{ street }})), '') is null then null
        else
            nullif(
                trim(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            regexp_replace(
                                                regexp_replace(
                                                    regexp_replace(
                                                        regexp_replace(
                                                            regexp_replace(
                                                                regexp_replace(
                                                                    regexp_replace(
                                                                        regexp_replace(
                                                                            regexp_replace(
                                                                                regexp_replace(
                                                                                    regexp_replace(
                                                                                        regexp_replace(lower({{ raw_address }}), '[''’]', '', 'g'),
                                                                                        '&',
                                                                                        ' and ',
                                                                                        'g'
                                                                                    ),
                                                                                    '\m(suite|ste|unit|apt|apartment)\s*#?\s*[a-z0-9-]+',
                                                                                    ' ',
                                                                                    'g'
                                                                                ),
                                                                                '#\s*[a-z0-9-]+',
                                                                                ' ',
                                                                                'g'
                                                                            ),
                                                                            '[^a-z0-9]+',
                                                                            ' ',
                                                                            'g'
                                                                        ),
                                                                        '\mstreet\M',
                                                                        ' st ',
                                                                        'g'
                                                                    ),
                                                                    '\mavenue\M',
                                                                    ' ave ',
                                                                    'g'
                                                                ),
                                                                '\mboulevard\M',
                                                                ' blvd ',
                                                                'g'
                                                            ),
                                                            '\broad\M',
                                                            ' rd ',
                                                            'g'
                                                        ),
                                                        '\mdrive\M',
                                                        ' dr ',
                                                        'g'
                                                    ),
                                                    '\mlane\M',
                                                    ' ln ',
                                                    'g'
                                                ),
                                                '\mcourt\M',
                                                ' ct ',
                                                'g'
                                            ),
                                            '\mplace\M',
                                            ' pl ',
                                            'g'
                                        ),
                                        '\mnorth\M',
                                        ' n ',
                                        'g'
                                    ),
                                    '\msouth\M',
                                    ' s ',
                                    'g'
                                ),
                                '\meast\M',
                                ' e ',
                                'g'
                            ),
                            '\mwest\M',
                            ' w ',
                            'g'
                        ),
                        '\s+',
                        ' ',
                        'g'
                    )
                ),
                ''
            )
        end
{% endmacro %}
