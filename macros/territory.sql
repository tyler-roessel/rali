{% macro territory(postcode, city) %}
    {#
      Coarse Chicago sales territory from ZIP and city. The ranges are a
      portfolio simplification, not official community areas. Unknown is a
      deliberate bucket so territory is never null.
    #}
    {% set zip = "left(regexp_replace(coalesce(" ~ postcode ~ ", ''), '\\D', '', 'g'), 5)" %}
    case
        when {{ zip }} ~ '^6060[1-7]$' then 'Chicago Downtown'
        when {{ zip }} ~ '^606(0[89]|1[0-6])$' then 'Chicago South'
        when {{ zip }} ~ '^606(1[7-9]|2[0-8])$' then 'Chicago Far South'
        when {{ zip }} ~ '^606(2[9]|3[0-9])$' then 'Chicago Southwest'
        when {{ zip }} ~ '^606(4[0-5])$' then 'Chicago North'
        when {{ zip }} ~ '^606(4[6-9]|5[0-9])$' then 'Chicago Northwest'
        when {{ zip }} = '60660' then 'Chicago North'
        when {{ zip }} = '60661' then 'Chicago Downtown'
        when {{ zip }} ~ '^606' then 'Chicago Other'
        when lower(coalesce(trim({{ city }}), '')) = 'chicago' then 'Chicago Other'
        when nullif(trim({{ city }}), '') is not null then 'Suburbs'
        else 'Unknown'
    end
{% endmacro %}
