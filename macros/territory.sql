{% macro territory(postcode, city) %}
    {#
      Coarse Dallas sales territory from ZIP and city. The buckets are a
      portfolio simplification, not official neighborhoods or council areas.
      Unknown is a deliberate bucket so territory is never null.
    #}
    {% set zip = "left(regexp_replace(coalesce(" ~ postcode ~ ", ''), '\\D', '', 'g'), 5)" %}
    case
        when {{ zip }} in (
            '75201', '75202', '75203', '75204', '75205', '75206',
            '75207', '75219', '75226'
        ) then 'Dallas Downtown'
        when {{ zip }} in ('75214', '75218', '75223', '75227', '75228')
            then 'Dallas East'
        when {{ zip }} in (
            '75208', '75210', '75211', '75212', '75215', '75216',
            '75217', '75224', '75232', '75233', '75236', '75237',
            '75241', '75249', '75253'
        ) then 'Dallas South'
        when {{ zip }} in (
            '75209', '75220', '75225', '75229', '75230', '75231',
            '75234', '75235', '75238', '75240', '75243', '75244',
            '75246', '75247', '75248', '75251', '75252', '75254',
            '75287', '75390'
        ) then 'Dallas North'
        when {{ zip }} ~ '^75[01]' then 'Dallas Metro'
        when lower(coalesce(trim({{ city }}), '')) = 'dallas' then 'Dallas Other'
        when nullif(trim({{ city }}), '') is not null then 'Suburbs'
        else 'Unknown'
    end
{% endmacro %}
