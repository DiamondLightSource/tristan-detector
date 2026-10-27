import json


class TristanMessageException(Exception):  # noqa: N818
    def __init__(self, msg, errno=None):
        self.msg = msg
        self.errno = errno

    def __str__(self):
        return str(self.msg)


class TristanMessage:
    msg_counter = 0

    MSG_ID = "msg_id"
    MSG_PARAMETERS = "parameters"
    MSG_TYPE = "msg_type"
    MSG_TYPE_GET = "get"
    MSG_TYPE_PUT = "put"
    MSG_TYPE_POST = "post"
    MSG_TYPE_RESPONSE = "response"

    RESPONSE_TYPE = "resp_type"
    MSG_DATA = "data"

    def __init__(self, msg_type=None, msg_id=None, from_str=None):
        self._attrs = {}

        if not from_str:
            self._attrs[self.MSG_TYPE] = msg_type
            self._attrs[self.MSG_ID] = msg_id
            self._attrs[self.MSG_PARAMETERS] = {}

        else:
            try:
                self._attrs = json.loads(from_str)

            except ValueError as e:
                raise TristanMessageException(
                    "Illegal message JSON format: " + str(e)
                ) from e

    @property
    def msg_type(self):
        return self._attrs[self.MSG_TYPE]

    @property
    def msg_id(self):
        return self._attrs[self.MSG_ID]

    @property
    def params(self):
        return self._attrs[self.MSG_PARAMETERS]

    def has_attribute(self, name):
        if name in self._attrs:
            return True
        return False

    def get_attribute(self, name):
        return self._attrs[name]

    def get_param(self, param_name):
        try:
            param_value = self._attrs[self.MSG_PARAMETERS][param_name]
        except KeyError:
            raise TristanMessageException("Missing parameter " + param_name) from None

        return param_value

    def set_param(self, param_name, param_value):
        if self.MSG_PARAMETERS not in self._attrs:
            self._attrs[self.MSG_PARAMETERS] = {}

        self._attrs[self.MSG_PARAMETERS][param_name] = param_value

    # @return a bytes-like object, not a string.
    def encode(self):
        return json.dumps(self._attrs).encode()

    def __eq__(self, other):
        return self._attrs == other.attrs

    def __ne__(self, other):
        return self._attrs != other.attrs

    def __str__(self):
        return json.dumps(self._attrs, sort_keys=True, indent=4, separators=(",", ": "))

    def __getitem__(self, attr_name):
        try:
            attr_value = self._attrs[attr_name]
        except KeyError:
            raise TristanMessageException("Missing attribute " + attr_name) from None

        return attr_value

    @staticmethod
    def new_id():
        TristanMessage.msg_counter += 1
        return TristanMessage.msg_counter

    @staticmethod
    def parse_json(raw_msg):
        msg = TristanMessage(from_str=raw_msg)
        if msg.msg_type == TristanMessage.MSG_TYPE_GET:
            reply_msg = GetMessage(msg.msg_id, msg.params)
        elif msg.msg_type == TristanMessage.MSG_TYPE_PUT:
            reply_msg = PutMessage(msg.msg_id, msg.params)
        elif msg.msg_type == TristanMessage.MSG_TYPE_POST:
            reply_msg = PostMessage(msg.msg_id, msg.params)
        elif msg.msg_type == TristanMessage.MSG_TYPE_RESPONSE:
            data = None
            if msg.has_attribute(TristanMessage.MSG_DATA):
                data = msg.get_attribute(TristanMessage.MSG_DATA)
            resp_type = None
            if msg.has_attribute(TristanMessage.RESPONSE_TYPE):
                resp_type = msg.get_attribute(TristanMessage.RESPONSE_TYPE)
                reply_msg = ResponseMessage(msg.msg_id, data, resp_type)
            else:
                reply_msg = ResponseMessage(msg.msg_id, data)
        else:
            raise TristanMessageException(
                f"Cannot parse unknown message type: {msg.msg_type}"
            )
        return reply_msg


class GetMessage(TristanMessage):
    def __init__(self, msg_id=None, params=None):
        if not msg_id:
            msg_id = TristanMessage.new_id()
        super().__init__(msg_type=TristanMessage.MSG_TYPE_GET, msg_id=msg_id)
        if params:
            self._attrs[self.MSG_PARAMETERS] = params


class PutMessage(TristanMessage):
    def __init__(self, msg_id=None, params=None):
        if not msg_id:
            msg_id = TristanMessage.new_id()
        super().__init__(msg_type=TristanMessage.MSG_TYPE_PUT, msg_id=msg_id)
        if params:
            self._attrs[self.MSG_PARAMETERS] = params


class PostMessage(TristanMessage):
    def __init__(self, msg_id=None, params=None):
        if not msg_id:
            msg_id = TristanMessage.new_id()
        super().__init__(msg_type=TristanMessage.MSG_TYPE_POST, msg_id=msg_id)
        if params:
            self._attrs[self.MSG_PARAMETERS] = params


class ResponseMessage(TristanMessage):
    RESPONSE_OK = 0
    RESPONSE_ERROR = 1

    def __init__(self, msg_id=None, data=None, response_type=RESPONSE_OK):
        if not msg_id:
            msg_id = TristanMessage.new_id()
        super().__init__(msg_type=TristanMessage.MSG_TYPE_RESPONSE, msg_id=msg_id)
        del self._attrs[self.MSG_PARAMETERS]
        self._attrs[self.RESPONSE_TYPE] = response_type
        if data:
            self._attrs[self.MSG_DATA] = data
        else:
            self._attrs[self.MSG_DATA] = {}

    @property
    def data(self):
        return self._attrs[self.MSG_DATA]
