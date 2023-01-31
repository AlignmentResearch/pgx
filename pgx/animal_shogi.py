from typing import Tuple

import jax
import jax.numpy as jnp
from flax import struct


# 指し手のdataclass
@struct.dataclass
class JaxAnimalShogiAction:
    # 上の3つは移動と駒打ちで共用
    # 下の3つは移動でのみ使用
    # 駒打ちかどうか
    is_drop: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # piece: 動かした(打った)駒の種類
    piece: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # final: 移動後の座標
    to: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # 移動前の座標
    from_: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # captured: 取られた駒の種類。駒が取られていない場合は0
    captured: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # is_promote: 駒を成るかどうかの判定
    is_promote: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)


# 盤面のdataclass
@struct.dataclass
class JaxAnimalShogiState:
    # turn 先手番なら0 後手番なら1
    turn: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # board 盤面の駒。
    # 空白,先手ヒヨコ,先手キリン,先手ゾウ,先手ライオン,先手ニワトリ,後手ヒヨコ,後手キリン,後手ゾウ,後手ライオン,後手ニワトリ
    # の順で駒がどの位置にあるかをone_hotで記録
    # ヒヨコ: Pawn, キリン: Rook, ゾウ: Bishop, ライオン: King, ニワトリ: Gold　と対応
    board: jnp.ndarray = jnp.zeros((11, 12), dtype=jnp.int32)
    # hand 持ち駒。先手ヒヨコ,先手キリン,先手ゾウ,後手ヒヨコ,後手キリン,後手ゾウの6種の値を増減させる
    hand: jnp.ndarray = jnp.zeros(6, dtype=jnp.int32)
    # legal_actions_black/white: 自殺手や王手放置などの手も含めた合法手の一覧
    # move/dropによって変化させる
    legal_actions_black: jnp.ndarray = jnp.zeros(180, dtype=jnp.int32)
    legal_actions_white: jnp.ndarray = jnp.zeros(180, dtype=jnp.int32)
    # checked: ターンプレイヤーの王に王手がかかっているかどうか
    is_check: jnp.ndarray = jnp.zeros(1, dtype=jnp.int32)
    # checking_piece: ターンプレイヤーに王手をかけている駒の座標
    checking_piece: jnp.ndarray = jnp.zeros(12, dtype=jnp.int32)


# BLACK/WHITE/(NONE)_○○_MOVEは22にいるときの各駒の動き
# 端にいる場合は対応するところに0をかけていけないようにする
BLACK_PAWN_MOVE = jnp.array([[0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]])
WHITE_PAWN_MOVE = jnp.array([[0, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0]])
BLACK_GOLD_MOVE = jnp.array([[1, 1, 0, 0], [1, 0, 1, 0], [1, 1, 0, 0]])
WHITE_GOLD_MOVE = jnp.array([[0, 1, 1, 0], [1, 0, 1, 0], [0, 1, 1, 0]])
ROOK_MOVE = jnp.array([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 0]])
BISHOP_MOVE = jnp.array([[1, 0, 1, 0], [0, 0, 0, 0], [1, 0, 1, 0]])
KING_MOVE = jnp.array([[1, 1, 1, 0], [1, 0, 1, 0], [1, 1, 1, 0]])


#  上下左右の辺に接しているかどうか
#  接している場合は後の関数で行ける場所を制限する
def _is_side(
    point,
):
    is_up = point % 4 == 0
    is_down = point % 4 == 3
    is_left = point >= 8
    is_right = point <= 3
    return is_up, is_down, is_left, is_right


# はみ出す部分をカットする
def _cut_outside(array, point):
    new_array = array
    u, d, l, r = _is_side(point)
    new_array = jax.lax.cond(
        u, lambda: new_array.at[:3, 0].set(0), lambda: new_array
    )
    new_array = jax.lax.cond(
        d, lambda: new_array.at[:3, 2].set(0), lambda: new_array
    )
    new_array = jax.lax.cond(
        r, lambda: new_array.at[0, :4].set(0), lambda: new_array
    )
    new_array = jax.lax.cond(
        l, lambda: new_array.at[2, :4].set(0), lambda: new_array
    )
    return new_array


def _action_board(array, point):
    new_array = array
    # point(0~11)を座標((0, 0)~(2, 3))に変換
    y, t = point // 4, point % 4
    new_array = _cut_outside(new_array, point)
    return jnp.roll(new_array, (y - 1, t - 1), axis=(0, 1))


#  座標と駒の種類から到達できる座標を列挙
POINT_MOVES = jnp.zeros((12, 11, 3, 4), dtype=jnp.int32)
for i in range(12):
    POINT_MOVES = POINT_MOVES.at[i, 1].set(_action_board(BLACK_PAWN_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 2].set(_action_board(ROOK_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 3].set(_action_board(BISHOP_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 4].set(_action_board(KING_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 5].set(_action_board(BLACK_GOLD_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 6].set(_action_board(WHITE_PAWN_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 7].set(_action_board(ROOK_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 8].set(_action_board(BISHOP_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 9].set(_action_board(KING_MOVE, i))
    POINT_MOVES = POINT_MOVES.at[i, 10].set(_action_board(WHITE_GOLD_MOVE, i))


INIT_BOARD = JaxAnimalShogiState(
    turn=jnp.array([0]),
    board=jnp.array(
        [
            [0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0],
            [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
            [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]
    ),
    hand=jnp.array([0, 0, 0, 0, 0, 0]),
)  # type: ignore


def init() -> JaxAnimalShogiState:
    return _init_legal_actions(INIT_BOARD)


def step(
    state: JaxAnimalShogiState, action: jnp.ndarray
) -> Tuple[JaxAnimalShogiState, int, bool]:
    # state, 勝敗判定,終了判定を返す
    s = state
    reward = 0
    terminated = False
    legal_actions = _legal_actions(s)
    # 合法手が存在しない場合、手番側の負けで終了
    # 途中でreturnができないならどちらにしろ非合法な手ではじかれるから要らない？
    # actionが合法手でない場合、手番側の負けで終了
    # actionのfromが盤外に存在すると挙動がおかしくなるのでそれもここではじいておく
    _action = _dlaction_to_action(action, s)
    reward = jax.lax.cond(
        (_action.from_[0] > 11)
        | (_action.from_[0] < 0)
        | (legal_actions[_action_to_dlaction(_action, s.turn[0])] == 0),
        lambda: _turn_to_reward(_another_color(s)),
        lambda: reward,
    )
    terminated = jax.lax.cond(
        (_action.from_[0] > 11)
        | (_action.from_[0] < 0)
        | (legal_actions[_action_to_dlaction(_action, s.turn[0])] == 0),
        lambda: True,
        lambda: terminated,
    )
    # actionが合法手の場合
    s = jax.lax.cond(
        terminated,
        lambda: s,
        lambda: jax.lax.cond(
            _action.is_drop[0] == 1,
            lambda: _drop(_update_legal_drop_actions(s, _action), _action),
            lambda: _move(_update_legal_move_actions(s, _action), _action),
        ),
    )
    # トライルールによる勝利判定
    reward = jax.lax.cond(
        (terminated is False) & _is_try(_action),
        lambda: _turn_to_reward(s.turn[0]),
        lambda: reward,
    )
    terminated = jax.lax.cond(
        (terminated is False) & _is_try(_action),
        lambda: True,
        lambda: terminated,
    )
    turn = jnp.zeros(1, dtype=jnp.int32).at[0].set(_another_color(s))
    s = JaxAnimalShogiState(
        turn=turn,
        board=s.board,
        hand=s.hand,
        legal_actions_black=s.legal_actions_black,
        legal_actions_white=s.legal_actions_white,
    )  # type: ignore
    no_checking_piece = jnp.zeros(12, dtype=jnp.int32)
    # 王手をかけている駒は直前に動かした駒であるはず
    checking_piece = no_checking_piece.at[_action.to[0]].set(1)
    s = jax.lax.cond(
        (_is_check(s)) & (terminated is False),
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=s.legal_actions_black,
            legal_actions_white=s.legal_actions_white,
            is_check=jnp.array([1]),
            checking_piece=checking_piece,
        ),  # type: ignore
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=s.legal_actions_black,
            legal_actions_white=s.legal_actions_white,
            is_check=jnp.array([0]),
            checking_piece=no_checking_piece,
        ),  # type: ignore
    )
    return s, reward, terminated


def _turn_to_reward(turn):
    reward = jax.lax.cond(
        turn == 0,
        lambda: 1,
        lambda: -1,
    )
    return reward


# dlshogiのactionはdirection(動きの方向)とto（駒の処理後の座標）に依存
def _dlshogi_action(direction, to):
    return direction * 12 + to


# fromの座標とtoの座標からdirを生成
def _point_to_direction(
    _from,
    to,
    promote,
    turn,
):
    direction = -1
    dis = to - _from
    # 後手番の動きは反転させる
    dis = jax.lax.cond(turn == 1, lambda: -dis, lambda: dis)
    # UP, UP_LEFT, UP_RIGHT, LEFT, RIGHT, DOWN, DOWN_LEFT, DOWN_RIGHT, UP_PROMOTE... の順でdirを割り振る
    # PROMOTEの場合は+8する処理を入れるが、どうぶつ将棋ではUP_PROMOTEしか存在しない(はず)
    direction = jax.lax.cond(dis == -1, lambda: 0, lambda: direction)
    direction = jax.lax.cond(dis == 3, lambda: 1, lambda: direction)
    direction = jax.lax.cond(dis == -5, lambda: 2, lambda: direction)
    direction = jax.lax.cond(dis == 4, lambda: 3, lambda: direction)
    direction = jax.lax.cond(dis == -4, lambda: 4, lambda: direction)
    direction = jax.lax.cond(dis == 1, lambda: 5, lambda: direction)
    direction = jax.lax.cond(dis == 5, lambda: 6, lambda: direction)
    direction = jax.lax.cond(dis == -3, lambda: 7, lambda: direction)
    direction = jax.lax.cond(
        promote == 1, lambda: direction + 8, lambda: direction
    )
    return direction


# 打った駒の種類をdirに変換
def _hand_to_direction(piece):
    # 移動のdirはPROMOTE_UPの8が最大なので9以降に配置
    # 9: 先手ヒヨコ 10: 先手キリン... 14: 後手ゾウ　に対応させる
    return jax.lax.cond(piece <= 5, lambda: 8 + piece, lambda: 6 + piece)


# AnimalShogiActionをdlshogiのint型actionに変換
def _action_to_dlaction(action: JaxAnimalShogiAction, turn):
    return jax.lax.cond(
        action.is_drop[0] == 1,
        lambda: _dlshogi_action(
            _hand_to_direction(action.piece[0]), action.to[0]
        ),
        lambda: _dlshogi_action(
            _point_to_direction(
                action.from_[0], action.to[0], action.is_promote[0], turn
            ),  # type: ignore
            action.to[0],
        ),
    )


# dlshogiのint型actionをdirectionとtoに分解
def _separate_dlaction(action):
    # direction, to の順番
    return action // 12, action % 12


# directionからfromがtoからどれだけ離れてるかと成りを含む移動かを得る
# 手番の情報が必要
def _direction_to_from(direction, to, turn):
    dif = 0
    dif = jax.lax.cond(
        (direction == 0) | (direction == 8), lambda: -1, lambda: dif
    )
    dif = jax.lax.cond(direction == 1, lambda: 3, lambda: dif)
    dif = jax.lax.cond(direction == 2, lambda: -5, lambda: dif)
    dif = jax.lax.cond(direction == 3, lambda: 4, lambda: dif)
    dif = jax.lax.cond(direction == 4, lambda: -4, lambda: dif)
    dif = jax.lax.cond(direction == 5, lambda: 1, lambda: dif)
    dif = jax.lax.cond(direction == 6, lambda: 5, lambda: dif)
    dif = jax.lax.cond(direction == 7, lambda: -3, lambda: dif)
    is_promote = jax.lax.cond(direction >= 8, lambda: 1, lambda: 0)
    _from = jax.lax.cond(turn == 0, lambda: to - dif, lambda: to + dif)
    return _from, is_promote


def _direction_to_hand(direction):
    return jax.lax.cond(
        direction <= 11, lambda: direction - 8, lambda: direction - 6
    )


def _dlmoveaction_to_action(
    action: jnp.ndarray, state: JaxAnimalShogiState
) -> JaxAnimalShogiAction:
    direction, to = _separate_dlaction(action)
    _from, is_promote = _direction_to_from(direction, to, state.turn[0])
    piece = _piece_type(state, _from)
    captured = _piece_type(state, to)
    return JaxAnimalShogiAction(
        is_drop=jnp.array([0]),
        piece=jnp.array([piece]),
        to=jnp.array([to]),
        from_=jnp.array([_from]),
        captured=jnp.array([captured]),
        is_promote=jnp.array([is_promote]),
    )  # type: ignore


def _dldropaction_to_action(action) -> JaxAnimalShogiAction:
    direction, to = _separate_dlaction(action)
    piece = _direction_to_hand(direction)
    return JaxAnimalShogiAction(
        is_drop=jnp.array([1]), piece=jnp.array([piece]), to=jnp.array([to])
    )  # type: ignore


def _dlaction_to_action(
    action, state: JaxAnimalShogiState
) -> JaxAnimalShogiAction:
    direction, to = _separate_dlaction(action)
    return jax.lax.cond(
        direction <= 8,
        lambda: _dlmoveaction_to_action(action, state),
        lambda: _dldropaction_to_action(action),
    )


# 手番側でない色を返す
def _another_color(state: JaxAnimalShogiState):
    return (state.turn[0] + 1) % 2


# 相手の駒を同じ種類の自分の駒に変換する
def _convert_piece(piece):
    # 両方の駒でない（＝空白）場合は-1を返す
    p = jax.lax.cond(piece == 0, lambda: -1, lambda: (piece + 5) % 10)
    return jax.lax.cond(p == 0, lambda: 10, lambda: p)


# 駒から持ち駒への変換
# 先手ひよこが0、後手ぞうが5
def _piece_to_hand(piece):
    p = jax.lax.cond(piece % 5 == 0, lambda: piece - 4, lambda: piece)
    return jax.lax.cond(p < 6, lambda: p - 1, lambda: p - 3)


#  移動の処理
def _move(
    state: JaxAnimalShogiState,
    action: JaxAnimalShogiAction,
) -> JaxAnimalShogiState:
    board = state.board
    hand = state.hand
    board = board.at[action.piece[0], action.from_[0]].set(0)
    board = board.at[0, action.from_[0]].set(1)
    board = board.at[action.captured[0], action.to[0]].set(0)
    board = jax.lax.cond(
        action.is_promote[0] == 1,
        lambda: board.at[action.piece[0] + 4, action.to[0]].set(1),
        lambda: board.at[action.piece[0], action.to[0]].set(1),
    )
    hand = jax.lax.cond(
        action.captured[0] == 0,
        lambda: hand,
        lambda: hand.at[
            _piece_to_hand(_convert_piece(action.captured[0]))
        ].set(hand[_piece_to_hand(_convert_piece(action.captured[0]))] + 1),
    )
    return JaxAnimalShogiState(
        turn=state.turn,
        board=board,
        hand=hand,
        legal_actions_black=state.legal_actions_black,
        legal_actions_white=state.legal_actions_white,
        is_check=state.is_check,
        checking_piece=state.checking_piece,
    )  # type: ignore


#  駒打ちの処理
def _drop(
    state: JaxAnimalShogiState, action: JaxAnimalShogiAction
) -> JaxAnimalShogiState:
    board = state.board
    hand = state.hand
    n = hand[_piece_to_hand(action.piece[0])]
    hand = hand.at[_piece_to_hand(action.piece[0])].set(n - 1)
    board = board.at[action.piece[0], action.to[0]].set(1)
    board = board.at[0, action.to[0]].set(0)
    return JaxAnimalShogiState(
        turn=state.turn,
        board=board,
        hand=hand,
        legal_actions_black=state.legal_actions_black,
        legal_actions_white=state.legal_actions_white,
        is_check=state.is_check,
        checking_piece=state.checking_piece,
    )  # type: ignore


#  ある座標に存在する駒種を返す
def _piece_type(state: JaxAnimalShogiState, point):
    return state.board[:, point].argmax()


# ある駒の持ち主を返す
def _owner(piece):
    return jax.lax.cond(piece == 0, lambda: 2, lambda: (piece - 1) // 5)


# 盤面のどこに何の駒があるかをnp.arrayに移したもの
# 同じ座標に複数回piece_typeを使用する場合はこちらを使った方が良い
def _board_status(state: JaxAnimalShogiState):
    return state.board.argmax(axis=0)


# 駒の持ち主の判定
def _pieces_owner(state: JaxAnimalShogiState):
    _piece_types = _board_status(state)
    board = jnp.where(_piece_types == 0, 2, (_piece_types - 1) // 5)
    return board


# 利きの判定
def _effected_positions(state: JaxAnimalShogiState, turn):
    all_effect = jnp.zeros(12, dtype=jnp.int32)
    board = _board_status(state)
    piece_owner = _pieces_owner(state)
    for i in range(12):
        own = piece_owner[i]
        piece = board[i]
        effect = POINT_MOVES[i, piece].reshape(12)
        all_effect = jax.lax.cond(
            own == turn, lambda: all_effect + effect, lambda: all_effect
        )
    return all_effect


# 王手の判定(turn側の王に王手がかかっているかを判定)
def _is_check(state: JaxAnimalShogiState):
    effects = _effected_positions(state, _another_color(state))
    king_location = state.board[4 + 5 * state.turn[0], :].argmax()
    return effects[king_location] != 0


# 成る動きが合法かどうかの判定
def _can_promote(to, piece):
    can_promote = False
    can_promote = jax.lax.cond(
        (piece == 1) & (to % 4 == 0),
        lambda: True,
        lambda: can_promote,
    )
    # can_promote = jax.lax.cond(
    #    piece == 1,
    #    lambda: jax.lax.cond(to % 4 == 0, lambda: True, lambda: can_promote),
    #    lambda: can_promote,
    # )
    can_promote = jax.lax.cond(
        (piece == 6) & (to % 4 == 3),
        lambda: True,
        lambda: can_promote,
    )
    # can_promote = jax.lax.cond(
    #    piece == 6,
    #    lambda: jax.lax.cond(to % 4 == 3, lambda: True, lambda: can_promote),
    #    lambda: can_promote,
    # )
    return can_promote


# 駒の種類と位置から生成できるactionのフラグを立てる
def _create_piece_actions(_from, piece):
    turn = _owner(piece)
    actions = jnp.zeros(180, dtype=jnp.int32)
    motion = POINT_MOVES[_from, piece].reshape(12)
    for i in range(12):
        normal_dir = _point_to_direction(_from, i, False, turn)
        normal_act = _dlshogi_action(normal_dir, i)
        pro_dir = _point_to_direction(_from, i, True, turn)
        pro_act = _dlshogi_action(pro_dir, i)
        actions = jax.lax.cond(
            motion[i] == 0,
            lambda: actions,
            lambda: jax.lax.cond(
                _can_promote(i, piece),
                lambda: actions.at[pro_act].set(1),
                lambda: actions,
            )
            .at[normal_act]
            .set(1),
        )
    return actions


# 駒の種類と位置から生成できるactionのフラグを立てる
def _add_move_actions(_from, piece, array):
    new_array = array
    actions = _create_piece_actions(_from, piece)
    new_array = jnp.where(actions == 1, 1, new_array)
    return new_array


# 駒の種類と位置から生成できるactionのフラグを折る
def _filter_move_actions(_from, piece, array):
    new_array = array
    actions = _create_piece_actions(_from, piece)
    new_array = jnp.where(actions == 1, 0, new_array)
    return new_array


# 駒打ちのactionを追加する
def _add_drop_actions(piece, array):
    new_array = array
    direction = _hand_to_direction(piece)
    new_array = jnp.where(jnp.arange(180) // 12 == direction, 1, new_array)
    return new_array


# 駒打ちのactionを消去する
def _filter_drop_actions(piece, array):
    new_array = array
    direction = _hand_to_direction(piece)
    new_array = jnp.where(jnp.arange(180) // 12 == direction, 0, new_array)
    return new_array


# stateからblack,white両方のlegal_actionsを生成する
# 普段は使わないがlegal_actionsが設定されていない場合に使用
def _init_legal_actions(state: JaxAnimalShogiState) -> JaxAnimalShogiState:
    pieces = _board_status(state)
    legal_black = state.legal_actions_black
    legal_white = state.legal_actions_white
    # 移動の追加
    legal_black = jax.lax.fori_loop(
        0,
        12,
        lambda i, x: jax.lax.cond(
            _owner(pieces[i]) == 0,
            lambda: _add_move_actions(i, pieces[i], x),
            lambda: x,
        ),
        legal_black,
    )
    legal_white = jax.lax.fori_loop(
        0,
        12,
        lambda i, x: jax.lax.cond(
            _owner(pieces[i]) == 1,
            lambda: _add_move_actions(i, pieces[i], x),
            lambda: x,
        ),
        legal_white,
    )
    # 駒打ちの追加
    for i in range(3):
        legal_black = jax.lax.cond(
            state.hand[i] == 0,
            lambda: legal_black,
            lambda: _add_drop_actions(1 + i, legal_black),
        )
        legal_white = jax.lax.cond(
            state.hand[i + 3] == 0,
            lambda: legal_white,
            lambda: _add_drop_actions(6 + i, legal_white),
        )
    return JaxAnimalShogiState(
        turn=state.turn,
        board=state.board,
        hand=state.hand,
        legal_actions_black=legal_black,
        legal_actions_white=legal_white,
        is_check=state.is_check,
        checking_piece=state.checking_piece,
    )  # type: ignore


# 駒の移動によるlegal_actionsの更新
def _update_legal_move_actions(
    state: JaxAnimalShogiState, action: JaxAnimalShogiAction
) -> JaxAnimalShogiState:
    s = state
    player_actions = jax.lax.cond(
        s.turn[0] == 0,
        lambda: s.legal_actions_black,
        lambda: s.legal_actions_white,
    )
    enemy_actions = jax.lax.cond(
        s.turn[0] == 0,
        lambda: s.legal_actions_white,
        lambda: s.legal_actions_black,
    )
    # 元の位置にいたときのフラグを折る
    new_player_actions = _filter_move_actions(
        action.from_[0], action.piece[0], player_actions
    )
    new_enemy_actions = enemy_actions
    # 移動後の位置からの移動のフラグを立てる
    new_player_actions = _add_move_actions(
        action.to[0], action.piece[0], new_player_actions
    )
    # 駒が取られた場合、相手の取られた駒によってできていたactionのフラグを折る
    new_enemy_actions = jax.lax.cond(
        action.captured[0] == 0,
        lambda: new_enemy_actions,
        lambda: _filter_move_actions(
            action.to[0], action.captured[0], new_enemy_actions
        ),
    )
    captured = _convert_piece(action.captured[0])
    captured = jax.lax.cond(
        captured % 5 == 0, lambda: captured - 4, lambda: captured
    )
    new_player_actions = jax.lax.cond(
        # capturedは何も取っていない場合は-1に変換されているはず
        captured == -1,
        lambda: new_player_actions,
        lambda: _add_drop_actions(captured, new_player_actions),
    )
    return jax.lax.cond(
        s.turn[0] == 0,
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=new_player_actions,
            legal_actions_white=new_enemy_actions,
            is_check=s.is_check,
            checking_piece=s.checking_piece,
        ),  # type: ignore
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=new_enemy_actions,
            legal_actions_white=new_player_actions,
            is_check=s.is_check,
            checking_piece=s.checking_piece,
        ),  # type: ignore
    )


# 駒打ちによるlegal_actionsの更新
def _update_legal_drop_actions(
    state: JaxAnimalShogiState, action: JaxAnimalShogiAction
) -> JaxAnimalShogiState:
    s = state
    player_actions = jax.lax.cond(
        s.turn[0] == 0,
        lambda: s.legal_actions_black,
        lambda: s.legal_actions_white,
    )
    # 移動後の位置からの移動のフラグを立てる
    new_player_actions = _add_move_actions(
        action.to[0], action.piece[0], player_actions
    )
    # 持ち駒がもうない場合、その駒を打つフラグを折る
    new_player_actions = jax.lax.cond(
        s.hand[_piece_to_hand(action.piece[0])] == 1,
        lambda: _filter_drop_actions(action.piece[0], new_player_actions),
        lambda: new_player_actions,
    )
    return jax.lax.cond(
        s.turn[0] == 0,
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=new_player_actions,
            legal_actions_white=s.legal_actions_white,
            is_check=s.is_check,
            checking_piece=s.checking_piece,
        ),  # type: ignore
        lambda: JaxAnimalShogiState(
            turn=s.turn,
            board=s.board,
            hand=s.hand,
            legal_actions_black=s.legal_actions_black,
            legal_actions_white=new_player_actions,
            is_check=s.is_check,
            checking_piece=s.checking_piece,
        ),  # type: ignore
    )


# 自分の駒がある位置への移動を除く
def _filter_my_piece_move_actions(turn, owner, array) -> jnp.ndarray:
    new_array = array
    ixs = jnp.arange(180)
    new_array = jnp.where(
        ((ixs // 12) < 9) & (owner[ixs % 12] == turn), 0, new_array
    )
    return new_array


# 駒がある地点への駒打ちを除く
def _filter_occupied_drop_actions(turn, owner, array) -> jnp.ndarray:
    new_array = array
    for i in range(12):
        for j in range(3):
            new_array = jax.lax.cond(
                owner[i] == 2,
                lambda: new_array,
                lambda: new_array.at[12 * (j + 9 + 3 * turn) + i].set(0),
            )
    return new_array


# 自殺手を除く
def _filter_suicide_actions(turn, king_sq, effects, array) -> jnp.ndarray:
    new_array = array
    king_moves = POINT_MOVES[4, king_sq].reshape(12)
    for i in range(12):
        new_array = jax.lax.cond(
            (king_moves[i] == 0) | (effects[i] == 0),
            lambda: new_array,
            lambda: new_array.at[
                _dlshogi_action(
                    _point_to_direction(king_sq, i, False, turn), i
                )
            ].set(0),
        )
    return new_array


# 王手放置を除く
def _filter_leave_check_actions(turn, king_sq, check_piece, array):
    new_array = array
    king_moves = POINT_MOVES[4, king_sq].reshape(12)
    for i in range(12):
        # 王手をかけている駒の位置以外への移動は王手放置

        # 駒打ちのフラグは全て折る
        new_array = jnp.where((jnp.arange(180) // 12) > 8, 0, new_array)
        # 王手をかけている駒の場所以外への移動ははじく
        new_array = jnp.where(
            check_piece[jnp.arange(180) % 12] == 0, 0, new_array
        )

        # 玉の移動はそれ以外でも可能だがフラグが折れてしまっているので立て直す
        new_array = jax.lax.cond(
            king_moves[i] == 0,
            lambda: new_array,
            lambda: new_array.at[
                _dlshogi_action(
                    _point_to_direction(king_sq, i, False, turn), i
                )
            ].set(1),
        )
    return new_array


# boardのlegal_actionsを利用して合法手を生成する
def _legal_actions(state: JaxAnimalShogiState) -> jnp.ndarray:
    s = state
    turn = s.turn[0]
    action_array = jax.lax.cond(
        turn == 0, lambda: s.legal_actions_black, lambda: s.legal_actions_white
    )
    king_sq = s.board[4 + 5 * turn].argmax()
    # 王手放置を除く
    action_array = jax.lax.cond(
        s.is_check[0] == 1,
        lambda: _filter_leave_check_actions(
            turn, king_sq, state.checking_piece, action_array
        ),
        lambda: action_array,
    )
    own = _pieces_owner(s)
    # 自分の駒がある位置への移動actionを除く
    action_array = _filter_my_piece_move_actions(turn, own, action_array)
    # 駒がある地点への駒打ちactionを除く
    action_array = _filter_occupied_drop_actions(turn, own, action_array)
    # 自殺手を除く
    effects = _effected_positions(s, _another_color(s))
    action_array = _filter_suicide_actions(
        turn, king_sq, effects, action_array
    )
    # その他の反則手を除く
    # どうぶつ将棋の場合はなし
    return action_array


# トライルールによる勝利判定
# 王が最奥に動くactionならTrue
def _is_try(action: JaxAnimalShogiAction) -> bool:
    flag = False
    flag = jax.lax.cond(
        (action.piece[0] == 4) & (action.to[0] % 4 == 0),
        lambda: True,
        lambda: flag,
    )
    flag = jax.lax.cond(
        (action.piece[0] == 9) & (action.to[0] % 4 == 3),
        lambda: True,
        lambda: flag,
    )
    return flag
