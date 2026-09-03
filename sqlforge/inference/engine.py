class NullInferenceEngine:
    def __init__(self, schema):
        self.schema = schema

    def infer(self, sql): ...


# https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md
