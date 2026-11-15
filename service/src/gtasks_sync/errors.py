class OpFailed(Exception):
    """The op can never succeed. It becomes a failed op and does not block later ops.

    Any other exception stops the round and keeps the op for the next round.
    """
