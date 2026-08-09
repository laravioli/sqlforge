def camel_case(s: str):
    return "".join(w.capitalize() for w in s.split("_"))
