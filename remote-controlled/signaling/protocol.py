import json
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, asdict


class MessageType(str, Enum):
    OFFER = "offer"
    ANSWER = "answer"
    ICE_CANDIDATE = "ice-candidate"
    CONTROL = "control"
    ERROR = "error"
    READY = "ready"


@dataclass
class SignalMessage:
    type: MessageType
    payload: dict[str, Any]
    client_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({"type": self.type.value, "payload": self.payload, "client_id": self.client_id})

    @classmethod
    def from_json(cls, data: str) -> "SignalMessage":
        obj = json.loads(data)
        return cls(
            type=MessageType(obj["type"]),
            payload=obj["payload"],
            client_id=obj.get("client_id")
        )


@dataclass
class OfferPayload:
    sdp: str
    type: str = "offer"


@dataclass
class AnswerPayload:
    sdp: str
    type: str = "answer"


@dataclass
class ICECandidatePayload:
    candidate: str
    sdpMid: str
    sdpMLineIndex: int


@dataclass
class ControlPayload:
    action: str
    data: dict[str, Any]


def create_offer_message(sdp: str, client_id: str = None) -> SignalMessage:
    return SignalMessage(MessageType.OFFER, {"sdp": sdp, "type": "offer"}, client_id)


def create_answer_message(sdp: str, client_id: str = None) -> SignalMessage:
    return SignalMessage(MessageType.ANSWER, {"sdp": sdp, "type": "answer"}, client_id)


def create_ice_message(candidate: str, sdp_mid: str, sdp_mline_index: int, client_id: str = None) -> SignalMessage:
    return SignalMessage(
        MessageType.ICE_CANDIDATE,
        {"candidate": candidate, "sdpMid": sdp_mid, "sdpMLineIndex": sdp_mline_index},
        client_id
    )


def create_control_message(action: str, data: dict, client_id: str = None) -> SignalMessage:
    return SignalMessage(MessageType.CONTROL, {"action": action, "data": data}, client_id)


def create_error_message(error: str, client_id: str = None) -> SignalMessage:
    return SignalMessage(MessageType.ERROR, {"error": error}, client_id)


def create_ready_message(client_id: str = None) -> SignalMessage:
    return SignalMessage(MessageType.READY, {}, client_id)