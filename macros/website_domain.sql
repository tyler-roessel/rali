{% macro website_domain(column) %}
    {#
      Normalize a website URL to the host used as the website_signals key.
      Mirrors extract/fingerprint_websites.py: lowercase, strip scheme, path,
      port, and leading www. No DNS or public-suffix logic.
    #}
    nullif(
        regexp_replace(
            split_part(
                split_part(
                    regexp_replace(lower(trim({{ column }})), '^https?://', ''),
                    '/',
                    1
                ),
                ':',
                1
            ),
            '^www\.',
            ''
        ),
        ''
    )
{% endmacro %}
