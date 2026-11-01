"""Conservative policy statement inspection, not an OCI authorization engine.

Only local Allow statements are interpreted. Original statements and unsupported
syntax are retained for review. Conditions are never evaluated.
"""

import re


def split_outside(text, delimiter):
    """Split outside quotes/braces; avoid matching a keyword inside a group name."""
    result, start, quote, depth, i = [], 0, None, 0, 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char in "{(":
            depth += 1
        elif char in "})":
            depth -= 1
        elif depth == 0 and text[i:i + len(delimiter)].casefold() == delimiter.casefold():
            result.append(text[start:i].strip())
            i += len(delimiter)
            start = i
            continue
        i += 1
    if quote or depth != 0:
        raise ValueError("Unbalanced quote or bracket")
    result.append(text[start:].strip())
    return result


def normalize_space(text):
    # Collapse whitespace outside quoted names, preserving quoted spaces exactly.
    return "".join(part if i % 2 else re.sub(r"\s+", " ", part)
                   for i, part in enumerate(re.split(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", text))).strip()


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def group_reference(subject):
    subject = re.sub(r"^group\s+", "", subject.strip(), flags=re.I)
    if re.match(r"^id\s+", subject, re.I):
        return {"ocid": re.sub(r"^id\s+", "", subject, flags=re.I).strip()}
    parts = split_outside(subject, "/")
    if len(parts) == 1:
        # Also accept a wholly quoted 'Domain/Group'.
        parts = unquote(parts[0]).split("/", 1)
    if len(parts) == 2:
        return {"domain": unquote(parts[0]), "name": unquote(parts[1])}
    return {"domain": "Default", "name": unquote(parts[0])}


def parse_statement(statement):
    try:
        text = normalize_space(statement)
        if not text.casefold().startswith("allow "):
            raise ValueError("Non-Allow statement (for example Define, Endorse or Admit)")
        parts = split_outside(text[6:], " to ")
        if len(parts) != 2:
            raise ValueError("Cannot isolate subject and action")
        subject, action = parts
        condition_parts = split_outside(action, " where ")
        if len(condition_parts) > 2:
            raise ValueError("Multiple top-level conditions")
        conditions = condition_parts[1] if len(condition_parts) == 2 else None
        scoped = split_outside(condition_parts[0], " in ")
        if len(scoped) != 2:
            raise ValueError("Unrecognized or missing scope")
        match = re.fullmatch(r"(inspect|read|use|manage)\s+([a-zA-Z0-9_-]+)", scoped[0], re.I)
        permissions = re.fullmatch(r"\{\s*[A-Z_]+(?:\s*,\s*[A-Z_]+)*\s*\}", scoped[0], re.I)
        if not match and not permissions:
            raise ValueError("Unrecognized verb/resource expression")
        if not (scoped[1].casefold() == "tenancy" or scoped[1].casefold().startswith("compartment ")):
            raise ValueError("Non-local or unrecognized scope")
        if subject.casefold().startswith("group "):
            kind = "group"
            refs = [group_reference(s) for s in split_outside(subject[6:], ",")]
            if not refs or any(not r.get("name", r.get("ocid")) for r in refs):
                raise ValueError("Empty group reference")
        elif subject.casefold() in ("any-user", "any-group"):
            kind, refs = subject.casefold(), []
        else:
            # Dynamic groups and service principals are not human IAM groups.
            kind, refs = "other-principal", []
        return {"parsed": True, "subject": subject, "subject_kind": kind, "group_refs": refs,
                "verb": match[1] if match else scoped[0], "resource_type": match[2] if match else None,
                "scope": scoped[1], "conditions": conditions}
    except ValueError as error:
        return {"parsed": False, "reason": str(error)}


def matches_group(parsed, group):
    for ref in parsed.get("group_refs", []):
        if "ocid" in ref:
            if group.get("ocid") and ref["ocid"] == group["ocid"]:
                return True
        elif (ref["domain"].casefold() == group["domain_name"].casefold()
              and ref["name"].casefold() == group["name"].casefold()):
            return True
    return False
