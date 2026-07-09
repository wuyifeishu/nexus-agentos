import json
import logging


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"msg": record.getMessage()})


class TraceContext:
    trace_id: str = ""
    span_id: str = ""
