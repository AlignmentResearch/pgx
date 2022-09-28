from typing import Tuple

import jax
from flax import struct
from jax import jit
from jax import numpy as jnp

BOARD_WIDTH = 5
BOARD_SIZE = BOARD_WIDTH * BOARD_WIDTH

BLACK = 0
WHITE = 1
POINT = 2
BLACK_CHAR = "@"
WHITE_CHAR = "O"
POINT_CHAR = "+"

NSEW = jnp.array([[-1, 0], [1, 0], [0, 1], [0, -1]])


@struct.dataclass
class MiniGoState:
    # 連
    ren_id_board: jnp.ndarray = jnp.full(
        (2, BOARD_SIZE), -1, dtype=int
    )  # type:ignore

    # 連idが使えるか
    available_ren_id: jnp.ndarray = jnp.ones((2, BOARD_SIZE), dtype=bool)

    # 連周りの情報 0:None 1:呼吸点 2:石
    liberty: jnp.ndarray = jnp.zeros((2, BOARD_SIZE, BOARD_SIZE), dtype=int)

    # 隣接している敵の連id
    adj_ren_id: jnp.ndarray = jnp.zeros(
        (2, BOARD_SIZE, BOARD_SIZE), dtype=bool
    )

    # 経過ターン, 0始まり
    turn: jnp.ndarray = jnp.zeros(1, dtype=int)

    # [0]: 黒の得たアゲハマ, [1]: 白の方
    agehama: jnp.ndarray = jnp.zeros(2, dtype=int)

    # 直前のactionがパスだとTrue
    passed: jnp.ndarray = jnp.zeros(1, dtype=bool)

    # コウによる着手禁止点(xy), 無ければ(-1)
    kou: jnp.ndarray = jnp.full(1, -1, dtype=int)  # type:ignore


@jit
def init() -> MiniGoState:
    return MiniGoState()


@jit
def step(
    state: MiniGoState, action: int
) -> Tuple[MiniGoState, jnp.ndarray, bool]:
    return jax.lax.cond(
        action < 0,
        lambda state, action: _pass_move(state),
        lambda state, action: _not_pass_move(state, action),
        state,
        action,
    )


@jit
def _pass_move(_state: MiniGoState) -> Tuple[MiniGoState, jnp.ndarray, bool]:
    return jax.lax.cond(
        _state.passed[0],
        lambda _state: (_add_turn(_state), _get_reward(_state), True),  # end
        lambda _state: (_add_pass(_state), jnp.array([0, 0]), False),
        _state,
    )


@jit
def _add_turn(_state: MiniGoState) -> MiniGoState:
    return MiniGoState(  # type:ignore
        ren_id_board=_state.ren_id_board,
        available_ren_id=_state.available_ren_id,
        liberty=_state.liberty,
        adj_ren_id=_state.adj_ren_id,
        turn=_state.turn.at[0].add(1),
        agehama=_state.agehama,
        passed=_state.passed,
        kou=_state.kou,
    )


@jit
def _add_pass(_state: MiniGoState) -> MiniGoState:
    return MiniGoState(  # type:ignore
        ren_id_board=_state.ren_id_board,
        available_ren_id=_state.available_ren_id,
        liberty=_state.liberty,
        adj_ren_id=_state.adj_ren_id,
        turn=_state.turn.at[0].add(1),
        agehama=_state.agehama,
        passed=_state.passed.at[0].set(True),
        kou=_state.kou,
    )


@jit
def _not_pass_move(
    _state: MiniGoState, _action: int
) -> Tuple[MiniGoState, jnp.ndarray, bool]:
    state = MiniGoState(  # type:ignore
        ren_id_board=_state.ren_id_board,
        available_ren_id=_state.available_ren_id,
        liberty=_state.liberty,
        adj_ren_id=_state.adj_ren_id,
        turn=_state.turn,
        agehama=_state.agehama,
        passed=_state.passed.at[0].set(False),
        kou=_state.kou,
    )
    xy = _action
    agehama_before = state.agehama[0]
    is_illegal = _is_illegal_move(state, xy)  # 既に他の石が置かれている or コウ

    # 石を置く
    kou_occurred = _kou_occurred(state, xy)
    state = _set_stone(state, xy)

    # 周囲の連を調べる
    for nsew in NSEW:  # type:ignore
        adj_pos = _xy_to_pos(xy) + nsew
        adj_xy = _pos_to_xy(adj_pos)
        state = jax.lax.cond(
            _is_off_board(adj_pos),
            lambda state, xy, adj_xy: state,  # 盤外
            lambda state, xy, adj_xy: jax.lax.cond(
                state.ren_id_board[_my_color(state), adj_xy] != -1,
                lambda state, xy, adj_xy: _merge_ren(state, xy, adj_xy),
                lambda state, xy, adj_xy: jax.lax.cond(
                    state.ren_id_board[_opponent_color(state), adj_xy] != -1,
                    lambda state, xy, adj_xy: _set_stone_next_to_oppo_ren(
                        state, xy, adj_xy
                    ),
                    lambda state, xy, adj_xy: MiniGoState(  # type:ignore
                        ren_id_board=state.ren_id_board,
                        available_ren_id=state.available_ren_id,
                        liberty=state.liberty.at[
                            _my_color(state),
                            state.ren_id_board[_my_color(state), xy],
                            adj_xy,
                        ].set(1),
                        adj_ren_id=state.adj_ren_id,
                        turn=state.turn,
                        agehama=state.agehama,
                        passed=state.passed,
                        kou=state.kou,
                    ),
                    state,
                    xy,
                    adj_xy,
                ),
                state,
                xy,
                adj_xy,
            ),
            state,
            xy,
            adj_xy,
        )

    # 自殺手
    is_illegal = (
        jnp.count_nonzero(
            state.liberty[
                _my_color(state), state.ren_id_board[_my_color(state), xy]
            ]
            == 1
        )
        == 0
    ) | is_illegal

    # コウの確認
    state = MiniGoState(  # type:ignore
        ren_id_board=state.ren_id_board,
        available_ren_id=state.available_ren_id,
        liberty=state.liberty,
        adj_ren_id=state.adj_ren_id,
        turn=state.turn,
        agehama=state.agehama,
        passed=state.passed,
        kou=state.kou.at[0].set(
            jax.lax.cond(
                kou_occurred
                & state.agehama[_my_color(_state)] - agehama_before
                == 1,
                lambda _: state.kou[0],
                lambda _: -1,
                0,
            )
        ),
    )

    return jax.lax.cond(
        is_illegal,
        lambda state: _illegal_move(state),
        lambda state: (_add_turn(state), jnp.array([0, 0]), False),
        state,
    )


@jit
def _is_illegal_move(_state: MiniGoState, _xy):
    """
    既に石があるorコウ
    """
    my_color = _my_color(_state)
    oppo_color = _opponent_color(_state)
    return jnp.logical_or(
        jnp.logical_or(
            _state.ren_id_board[my_color, _xy] != -1,
            _state.ren_id_board[oppo_color, _xy] != -1,
        ),
        _xy == _state.kou[0],
    )


@jit
def _my_color(_state: MiniGoState):
    return _state.turn[0] % 2


@jit
def _illegal_move(
    _state: MiniGoState,
) -> Tuple[MiniGoState, jnp.ndarray, bool]:
    r: jnp.ndarray = jnp.array([1, 1])  # type:ignore
    return _add_turn(_state), r.at[_state.turn[0] % 2].set(-1), True


@jit
def _set_stone(_state: MiniGoState, _xy: int):
    available_ren_id = _state.available_ren_id.at[_my_color(_state)].get()
    next_ren_id = jnp.argmax(available_ren_id)
    available_ren_id = available_ren_id.at[next_ren_id].set(False)
    return MiniGoState(  # type:ignore
        _state.ren_id_board.at[_my_color(_state), _xy].set(next_ren_id),
        _state.available_ren_id.at[_my_color(_state)].set(available_ren_id),
        _state.liberty,
        _state.adj_ren_id,
        _state.turn,
        _state.agehama,
        _state.passed,
        _state.kou,
    )


@jit
def _merge_ren(_state: MiniGoState, _xy: int, _adj_xy: int):
    ren_id_board = _state.ren_id_board.at[_my_color(_state)].get()

    new_id = ren_id_board.at[_xy].get()
    adj_ren_id = ren_id_board.at[_adj_xy].get()

    small_id, large_id = jax.lax.cond(
        adj_ren_id < new_id,
        lambda _: (adj_ren_id, new_id),
        lambda _: (new_id, adj_ren_id),
        0,
    )
    # 大きいidの連を消し、小さいidの連と繋げる

    ren_id_board = jnp.where(ren_id_board == large_id, small_id, ren_id_board)

    liberty = _state.liberty.at[_my_color(_state)].get()
    liberty = liberty.at[large_id, _xy].set(0)
    liberty = liberty.at[small_id, _xy].set(0)
    liberty = liberty.at[small_id].set(
        jnp.maximum(liberty[small_id], liberty[large_id])
    )
    liberty = liberty.at[large_id].set(jnp.zeros(BOARD_SIZE, dtype=bool))

    _adj_ren_id = _state.adj_ren_id.at[_my_color(_state)].get()

    _oppo_adj_ren_id = jax.lax.map(
        lambda _a: jnp.where(
            _a[large_id], _a.at[large_id].set(False).at[small_id].set(True), _a
        ),
        _state.adj_ren_id.at[_opponent_color(_state)].get(),
    )
    _adj_ren_id = _adj_ren_id.at[small_id].set(
        jnp.logical_or(_adj_ren_id[small_id], _adj_ren_id[large_id])
    )
    _adj_ren_id = _adj_ren_id.at[large_id].set(
        jnp.zeros(BOARD_SIZE, dtype=bool)
    )

    return jax.lax.cond(
        new_id == adj_ren_id,
        lambda _state, liberty: _state,
        lambda _state, liberty: MiniGoState(  # type:ignore
            _state.ren_id_board.at[_my_color(_state)].set(ren_id_board),
            _state.available_ren_id.at[_my_color(_state), large_id].set(True),
            _state.liberty.at[_my_color(_state)].set(liberty),
            _state.adj_ren_id.at[_my_color(_state)]
            .set(_adj_ren_id)
            .at[_opponent_color(_state)]
            .set(_oppo_adj_ren_id),
            _state.turn,
            _state.agehama,
            _state.passed,
            _state.kou,
        ),
        _state,
        liberty,
    )


@jit
def _set_stone_next_to_oppo_ren(_state: MiniGoState, _xy, _adj_xy):
    oppo_ren_id = _state.ren_id_board.at[
        _opponent_color(_state), _adj_xy
    ].get()

    liberty = (
        _state.liberty.at[_opponent_color(_state), oppo_ren_id, _xy]
        .set(2)
        .at[
            _my_color(_state),
            _state.ren_id_board[_my_color(_state), _xy],
            _adj_xy,
        ]
        .set(2)
    )
    adj_ren_id = (
        _state.adj_ren_id.at[
            _my_color(_state),
            _state.ren_id_board[_my_color(_state), _xy],
            oppo_ren_id,
        ]
        .set(True)
        .at[
            _opponent_color(_state),
            oppo_ren_id,
            _state.ren_id_board[_my_color(_state), _xy],
        ]
        .set(True)
    )

    state = MiniGoState(  # type:ignore
        _state.ren_id_board,
        _state.available_ren_id,
        liberty,
        adj_ren_id,
        _state.turn,
        _state.agehama,
        _state.passed,
        _state.kou,
    )

    return jax.lax.cond(
        jnp.count_nonzero(
            state.liberty[_opponent_color(state), oppo_ren_id] == 1
        )
        == 0,
        lambda state, oppo_ren_id, _adj_xy: _remove_stones(
            state, oppo_ren_id, _adj_xy
        ),
        lambda state, oppo_ren_id, _adj_xy: state,
        state,
        oppo_ren_id,
        _adj_xy,
    )


@jit
def _remove_stones(_state: MiniGoState, _rm_ren_id, _rm_stone_xy):
    surrounded_stones = (
        _state.ren_id_board[_opponent_color(_state)] == _rm_ren_id
    )
    agehama = jnp.count_nonzero(surrounded_stones)
    oppo_ren_id_board = jnp.where(
        surrounded_stones, -1, _state.ren_id_board[_opponent_color(_state)]
    )
    liberty = jax.lax.map(
        lambda l: jnp.where((l > 0) & surrounded_stones, 1, l),
        _state.liberty[_my_color(_state)],
    )
    available_ren_id = _state.available_ren_id.at[
        _opponent_color(_state), _rm_ren_id
    ].set(True)

    return MiniGoState(  # type:ignore
        _state.ren_id_board.at[_opponent_color(_state)].set(oppo_ren_id_board),
        available_ren_id,
        _state.liberty.at[_my_color(_state)]
        .set(liberty)
        .at[_opponent_color(_state), _rm_ren_id, :]
        .set(0),
        _state.adj_ren_id.at[_opponent_color(_state), _rm_ren_id]
        .set(jnp.zeros(BOARD_SIZE, dtype=bool))
        .at[_my_color(_state), :, _rm_ren_id]
        .set(False),
        _state.turn,
        _state.agehama.at[_my_color(_state)].add(agehama),
        _state.passed,
        _state.kou.at[0].set(_rm_stone_xy),
    )


@jit
def legal_actions(state: MiniGoState) -> jnp.ndarray:
    return jnp.logical_not(
        jax.lax.map(lambda xy: step(state, xy), jnp.arange(BOARD_SIZE))[2]
    )


@jit
def get_board(state: MiniGoState) -> jnp.ndarray:
    board = jnp.full(BOARD_SIZE, 2)
    board = jnp.where(state.ren_id_board[BLACK] != -1, 0, board)
    board = jnp.where(state.ren_id_board[WHITE] != -1, 1, board)
    return board  # type:ignore


def show(state: MiniGoState) -> None:
    print("===========")

    for i in range(BOARD_WIDTH):
        for j in range(BOARD_WIDTH):
            if state.ren_id_board[BLACK][_to_xy(i, j)] != -1:
                print(" " + BLACK_CHAR, end="")
            elif state.ren_id_board[WHITE][_to_xy(i, j)] != -1:
                print(" " + WHITE_CHAR, end="")
            else:
                print(" " + POINT_CHAR, end="")
        print("")


def _show_details(state: MiniGoState) -> None:
    show(state)
    print(state.ren_id_board[BLACK].reshape((5, 5)))
    print(state.ren_id_board[WHITE].reshape((5, 5)))
    print(state.kou[0])


@jit
def _is_off_board(_pos: jnp.ndarray) -> bool:
    return jnp.logical_not(_is_on_board(_pos))


@jit
def _is_on_board(_pos: jnp.ndarray) -> bool:
    x = _pos[0]
    y = _pos[1]
    return jnp.logical_and(
        jnp.logical_and(x >= 0, BOARD_WIDTH > x),
        jnp.logical_and(y >= 0, BOARD_WIDTH > y),
    )


@jit
def _pos_to_xy(pos: jnp.ndarray) -> int:
    return pos[0] * BOARD_WIDTH + pos[1]


@jit
def _to_xy(x, y) -> int:
    return x * BOARD_WIDTH + y


@jit
def _xy_to_pos(xy):
    return jnp.array([xy // BOARD_WIDTH, xy % BOARD_WIDTH])


@jit
def _opponent_color(_state: MiniGoState) -> int:
    return (_state.turn[0] + 1) % 2


@jit
def _kou_occurred(_state: MiniGoState, xy: int) -> bool:
    x = xy // BOARD_WIDTH
    y = xy % BOARD_WIDTH
    oppo_color = _opponent_color(_state)

    return jnp.logical_and(
        jnp.logical_and(
            jnp.logical_and(
                jnp.logical_or(
                    x < 0,
                    _state.ren_id_board[oppo_color][_to_xy(x - 1, y)] != -1,
                ),
                jnp.logical_or(
                    x >= BOARD_SIZE - 1,
                    _state.ren_id_board[oppo_color][_to_xy(x + 1, y)] != -1,
                ),
            ),
            jnp.logical_or(
                y < 0,
                _state.ren_id_board[oppo_color][_to_xy(x, y - 1)] != -1,
            ),
        ),
        jnp.logical_or(
            y >= BOARD_SIZE - 1,
            _state.ren_id_board[oppo_color][_to_xy(x, y + 1)] != -1,
        ),
    )


@jit
def _get_reward(state: MiniGoState) -> jnp.ndarray:
    b = _count_ji(state, BLACK) - state.agehama[WHITE]
    w = _count_ji(state, WHITE) - state.agehama[BLACK]
    r = jax.lax.cond(
        b == w, lambda _: jnp.array([0, 0]), lambda _: jnp.array([-1, 1]), 0
    )
    r = jax.lax.cond(b > w, lambda r: jnp.array([1, -1]), lambda r: r, r)

    return r


@jit
def _count_ji(_state: MiniGoState, _color):
    board = get_board(_state)
    return jnp.count_nonzero(_get_surrounded_stones(board, _color))


@struct.dataclass
class JI:
    board: jnp.ndarray
    candidate_xy: jnp.ndarray
    examined_stones: jnp.ndarray
    color: jnp.ndarray


@jit
def _get_surrounded_stones(_board: jnp.ndarray, color: int):
    # 1. boardの一番外側に1周分追加
    board = jnp.pad(
        _board.reshape((BOARD_WIDTH, BOARD_WIDTH)),
        1,
        "constant",
        constant_values=-1,
    )
    # こうなる
    # [[-1 -1 -1 -1 -1 -1 -1]
    #  [-1  2  2  2  2  2 -1]
    #  [-1  2  2  2  2  2 -1]
    #  [-1  2  2  2  2  2 -1]
    #  [-1  2  2  2  2  2 -1]
    #  [-1  2  2  2  2  2 -1]
    #  [-1 -1 -1 -1 -1 -1 -1]]
    board = board.ravel()

    # 2. oppo_colorに隣り合う空点をoppo_colorに置き換える
    candidate_xy = board == (color + 1) % 2
    examined_stones: jnp.ndarray = jnp.zeros_like(board, dtype=bool)

    ji = JI(
        board,
        candidate_xy,
        examined_stones,
        jnp.array([color], dtype=int),  # type:ignore
    )

    ji = jax.lax.while_loop(
        lambda ji: jnp.count_nonzero(ji.candidate_xy) != 0, _count_ji_roop, ji
    )
    board = ji.board.reshape((BOARD_WIDTH + 2, BOARD_WIDTH + 2))

    # 3. 増やした外側をカットし、残った空点がcolorの地となる
    return board[1 : BOARD_WIDTH + 1, 1 : BOARD_WIDTH + 1] == POINT


@jit
def _count_ji_roop(_ji: JI) -> JI:
    board = _ji.board
    xy = jnp.nonzero(_ji.candidate_xy, size=1)[0][0]
    candidate_xy = _ji.candidate_xy.at[xy].set(False)
    o_color = (_ji.color[0] + 1) % 2
    _BOARD_WIDTH = BOARD_WIDTH + 2

    # この座標は「既に調べたリスト」へ
    examined_stones = _ji.examined_stones.at[xy].set(True)

    board = board.at[xy - _BOARD_WIDTH].set(
        jax.lax.cond(
            board[xy - _BOARD_WIDTH] == POINT,
            lambda board, xy, o_color: o_color,
            lambda board, xy, o_color: board[xy - _BOARD_WIDTH],
            board,
            xy,
            o_color,
        )
    )
    candidate_xy = candidate_xy.at[xy - _BOARD_WIDTH].set(
        jnp.logical_and(
            board[xy - _BOARD_WIDTH] == o_color,
            examined_stones[xy - _BOARD_WIDTH] is False,
        )
    )

    board = board.at[xy + _BOARD_WIDTH].set(
        jax.lax.cond(
            board[xy + _BOARD_WIDTH] == POINT,
            lambda board, xy, o_color: o_color,
            lambda board, xy, o_color: board[xy + _BOARD_WIDTH],
            board,
            xy,
            o_color,
        )
    )
    candidate_xy = candidate_xy.at[xy + _BOARD_WIDTH].set(
        jnp.logical_and(
            board[xy + _BOARD_WIDTH] == o_color,
            examined_stones[xy + _BOARD_WIDTH] is False,
        )
    )

    board = board.at[xy - 1].set(
        jax.lax.cond(
            board[xy - 1] == POINT,
            lambda board, xy, o_color: o_color,
            lambda board, xy, o_color: board[xy - 1],
            board,
            xy,
            o_color,
        )
    )
    candidate_xy = candidate_xy.at[xy - 1].set(
        jnp.logical_and(
            board[xy - 1] == o_color,
            examined_stones[xy - 1] is False,
        )
    )

    board = board.at[xy + 1].set(
        jax.lax.cond(
            board[xy + 1] == POINT,
            lambda board, xy, o_color: o_color,
            lambda board, xy, o_color: board[xy + 1],
            board,
            xy,
            o_color,
        )
    )
    candidate_xy = candidate_xy.at[xy + 1].set(
        jnp.logical_and(
            board[xy + 1] == o_color,
            examined_stones[xy + 1] is False,
        )
    )
    return JI(board, candidate_xy, examined_stones, _ji.color)  # type:ignore
