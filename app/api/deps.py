from fastapi import Request


def get_conn(request: Request):
    return request.app.state.conn


def get_registry(request: Request):
    return request.app.state.registry
