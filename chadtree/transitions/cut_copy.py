from itertools import chain
from os import linesep
from pathlib import PurePath
from typing import AbstractSet, Awaitable, Callable, Mapping, MutableMapping, Optional

from pynvim_pp.nvim import Nvim
from std2 import anext
from std2.locale import pathsort_key

from ..fs.cartographer import is_dir
from ..fs.ops import ancestors, copy, cut, exists, unify_ancestors
from ..fs.types import Node
from ..lsp.notify import lsp_created, lsp_moved
from ..registry import rpc
from ..settings.localization import LANG
from ..settings.types import Settings
from ..state.next import forward
from ..state.types import State
from ..view.ops import display_path
from .shared.index import indices
from .shared.refresh import refresh
from .shared.wm import kill_buffers
from .types import Stage


def _find_dest(src: PurePath, node: Node) -> PurePath:
    parent = node.path if is_dir(node) else node.path.parent
    dst = parent / src.name
    return dst


async def _operation(
    *,
    state: State,
    settings: Settings,
    is_visual: bool,
    nono: AbstractSet[PurePath],
    op_name: str,
    is_move: bool,
    action: Callable[[Mapping[PurePath, PurePath]], Awaitable[None]],
) -> Optional[Stage]:
    node = await anext(indices(state, is_visual=is_visual), None)
    selection = state.selection
    unified = unify_ancestors(selection)

    if not unified or not node:
        await Nvim.write(LANG("nothing_select"), error=True)
        return None
    elif not unified.isdisjoint(nono):
        await Nvim.write(LANG("operation not permitted on root"), error=True)
        return None
    else:
        pre_operations = {src: _find_dest(src, node) for src in unified}
        pre_existing = {
            s: d for s, d in pre_operations.items() if await exists(d, follow=False)
        }

        new_operations: MutableMapping[PurePath, PurePath] = {}
        while pre_existing:
            source, dest = pre_existing.popitem()
            resp = await Nvim.input(question=LANG("path_exists_err"), default=dest.name)
            new_dest = dest.parent / resp if resp else None

            if not new_dest:
                pre_existing[source] = dest
                break
            elif await exists(new_dest, follow=False):
                pre_existing[source] = new_dest
            else:
                new_operations[source] = new_dest

        if pre_existing:
            msg = linesep.join(
                f"{display_path(s, state=state)} -> {display_path(d, state=state)}"
                for s, d in sorted(
                    pre_existing.items(), key=lambda t: pathsort_key(t[0])
                )
            )
            await Nvim.write(
                LANG("paths already exist", operation=op_name, paths=msg),
                error=True,
            )
            return None

        else:
            operations = {**pre_operations, **new_operations}
            msg = linesep.join(
                f"{display_path(s, state=state)} -> {display_path(d, state=state)}"
                for s, d in sorted(operations.items(), key=lambda t: pathsort_key(t[0]))
            )

            question = LANG("confirm op", operation=op_name, paths=msg)
            ans = await Nvim.confirm(
                question=question,
                answers=LANG("ask_yesno"),
                answer_key={1: True, 2: False},
            )

            if not ans:
                return None
            else:
                try:
                    await action(operations)
                except Exception as e:
                    await Nvim.write(e, error=True)
                    return await refresh(state, settings=settings)
                else:
                    paths = {
                        p.parent for p in chain(operations.keys(), operations.values())
                    }
                    index = state.index | paths
                    new_selection = {*operations.values()}
                    new_state = await forward(
                        state,
                        settings=settings,
                        index=index,
                        selection=new_selection,
                        paths=paths,
                    )
                    focus = next(
                        iter(sorted(new_selection, key=pathsort_key)),
                        None,
                    )

                    if is_move:
                        await kill_buffers(
                            last_used=new_state.window_order,
                            paths=selection,
                            reopen={},
                        )
                        await lsp_moved(operations)
                    else:
                        await lsp_created(new_selection)
                    return Stage(new_state, focus=focus)


@rpc(blocking=False)
async def _cut(state: State, settings: Settings, is_visual: bool) -> Optional[Stage]:
    """
    Cut selected
    """

    cwd, root = await Nvim.getcwd(), state.root.path
    nono = {cwd, root} | ancestors(cwd, root)
    return await _operation(
        state=state,
        settings=settings,
        is_visual=is_visual,
        nono=nono,
        op_name=LANG("cut"),
        action=cut,
        is_move=True,
    )


@rpc(blocking=False)
async def _copy(state: State, settings: Settings, is_visual: bool) -> Optional[Stage]:
    """
    Copy selected
    """

    return await _operation(
        state=state,
        settings=settings,
        is_visual=is_visual,
        nono=set(),
        op_name=LANG("copy"),
        action=copy,
        is_move=False,
    )
