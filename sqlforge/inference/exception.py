class BottomException(Exception):
    """
    raise Bottom exception in place of a bottom element
    """


class SimplificationError(Exception): ...


class StarNotExpanded(Exception): ...


class SchemaError(Exception): ...


class JoinNotInferred(Exception): ...
