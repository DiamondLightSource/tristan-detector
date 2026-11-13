from tristan_detector.control.tristan_channel import TristanChannel


def test_dealer_does_not_queue_messages_without_a_peer():
    # Nothing listens here, so nothing should be queued for later delivery
    channel = TristanChannel(TristanChannel.CHANNEL_TYPE_DEALER)
    channel.connect("tcp://127.0.0.1:59998")
    try:
        assert [channel.send(b"x") for _ in range(3)] == [-1, -1, -1]
    finally:
        channel.close()
