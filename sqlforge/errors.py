class SqlforgeError(Exception):
    pass


class ConfigError(SqlforgeError):
    pass


class LoaderError(SqlforgeError):
    pass
