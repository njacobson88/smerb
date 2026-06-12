"""Safe substitution for user-authored compliance-message templates.

The dashboard lets staff write custom subject/body templates with `{name}`-style
placeholders. Rendering them with the builtin `str.format(**vars)` is unsafe:
`str.format` honors attribute and index access, so a template like
`{name.__class__.__init__.__globals__[...]}` walks into module globals and can
exfiltrate secrets/config. This module substitutes ONLY whitelisted top-level
field names and refuses any placeholder that uses attribute (`.`) or index (`[`)
access — closing the format-string injection while preserving normal `{field}`
and `{field:spec}` usage.
"""
import re
import string

_FIELD_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def safe_format(template, variables):
    """Render `template`, substituting only simple `{field}` placeholders whose
    name is a key in `variables`. Raises ValueError on any unsupported or
    unknown placeholder (attribute/index access, positional `{}`, or unknown
    name) instead of leaking. Non-string templates are returned unchanged.
    """
    if not isinstance(template, str):
        return template

    out = []
    for literal, field, spec, conv in string.Formatter().parse(template):
        out.append(literal)
        if field is None:
            continue
        if not _FIELD_RE.match(field):
            # "", "name.attr", "name[0]", "0" (positional) all rejected here.
            raise ValueError(f"Unsupported placeholder in template: '{{{field}}}'")
        if field not in variables:
            raise ValueError(f"Unknown placeholder in template: '{{{field}}}'")
        if spec and "{" in spec:
            # nested replacement field inside the format spec — reject.
            raise ValueError("Nested format specs are not allowed")
        value = variables[field]
        if conv == "r":
            value = repr(value)
        elif conv == "a":
            value = ascii(value)
        out.append(format(value, spec) if spec else str(value))
    return "".join(out)
