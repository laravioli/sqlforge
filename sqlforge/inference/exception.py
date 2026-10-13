class Unsupported(Exception):
    pass


class ByPassed(Unsupported):
    pass


class UnknownColumn(Unsupported):
    pass


class StarNotExpanded(Unsupported):
    pass
