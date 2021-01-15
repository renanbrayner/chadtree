from os import listdir, stat
from os.path import basename, join, splitext
from stat import (
    S_IEXEC,
    S_ISDIR,
    S_ISFIFO,
    S_ISGID,
    S_ISLNK,
    S_ISREG,
    S_ISSOCK,
    S_ISUID,
    S_ISVTX,
    S_IWOTH,
)
from typing import AbstractSet, Iterator, Mapping, cast

from ..state.types import Index
from .types import Mode, Node

_FILE_MODES: Mapping[int, Mode] = {
    S_IEXEC: Mode.executable,
    S_IWOTH: Mode.other_writable,
    S_ISVTX: Mode.sticky_dir,
    S_ISGID: Mode.set_gid,
    S_ISUID: Mode.set_uid,
}


def _fs_modes(stat: int) -> Iterator[Mode]:
    if S_ISDIR(stat):
        yield Mode.folder
    if S_ISREG(stat):
        yield Mode.file
    if S_ISFIFO(stat):
        yield Mode.pipe
    if S_ISSOCK(stat):
        yield Mode.socket
    for bit, mode in _FILE_MODES.items():
        if stat & bit == bit:
            yield mode


def _fs_stat(path: str) -> AbstractSet[Mode]:
    try:
        info = stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return {Mode.orphan_link}
    else:
        if S_ISLNK(info.st_mode):
            try:
                link_info = stat(path, follow_symlinks=True)
            except FileNotFoundError:
                return {Mode.orphan_link}
            else:
                mode = {*_fs_modes(link_info.st_mode)}
                return mode | {Mode.link}
        else:
            mode = {*_fs_modes(info.st_mode)}
            return mode


def new(root: str, index: Index) -> Node:
    mode = _fs_stat(root)
    name = basename(root)
    if Mode.folder not in mode:
        _, ext = splitext(name)
        return Node(path=root, mode=mode, name=name, ext=ext)

    elif root in index:
        children = {
            path: new(path, index=index)
            for path in (join(root, d) for d in listdir(root))
        }
        return Node(path=root, mode=mode, name=name, children=children)
    else:
        return Node(path=root, mode=mode, name=name)


def _update(root: Node, index: Index, paths: AbstractSet[str]) -> Node:
    if root.path in paths:
        return new(root.path, index=index)
    else:
        children = {
            k: _update(v, index=index, paths=paths)
            for k, v in (root.children or cast(Mapping[str, Node], {})).items()
        }
        return Node(
            path=root.path,
            mode=root.mode,
            name=root.name,
            children=children,
            ext=root.ext,
        )


def update(root: Node, *, index: Index, paths: AbstractSet[str]) -> Node:
    try:
        return _update(root, index=index, paths=paths)
    except FileNotFoundError:
        return new(root.path, index=index)


def is_dir(node: Node) -> bool:
    return Mode.folder in node.mode
