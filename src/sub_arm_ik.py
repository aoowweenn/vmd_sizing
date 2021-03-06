# -*- coding: utf-8 -*-
# 腕IK処理
# 
import logging
import copy
from math import acos, degrees
from PyQt5.QtGui import QQuaternion, QVector3D, QVector2D, QMatrix4x4, QVector4D

from VmdWriter import VmdWriter, VmdBoneFrame
from VmdReader import VmdReader
from PmxModel import PmxModel, SizingException
from PmxReader import PmxReader
import utils
import sub_move

logger = logging.getLogger("VmdSizing").getChild(__name__)

# file_logger = logging.getLogger("message")
# file_logger.addHandler(logging.FileHandler("test.csv"))

def exec(motion, trace_model, replace_model, output_vmd_path, is_avoidance, is_hand_ik, hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, hand_floor_distance, leg_floor_distance, is_finger_ik, finger_distance, org_motion_frames):
    is_error_outputed = False

    # -----------------------------------------------------------------
    # 手首位置合わせ処理
    if motion.motion_cnt > 0 and not is_avoidance and is_hand_ik:

        if not trace_model.can_arm_sizing or not replace_model.can_arm_sizing:
            # 腕構造チェックがFALSEの場合、腕IK補正なし
            return False
        elif is_finger_ik and (("左親指０" in motion.frames and "左親指０" not in replace_model.bones) or ("右親指０" in motion.frames and "右親指０" not in replace_model.bones)):
            print("■■■■■■■■■■■■■■■■■")
            print("■　**WARNING**　")
            print("■　モーションに「親指０」が登録されており、変換先モデルに「親指０」がありません。")
            print("■　指位置合わせをスキップします。")
            print("■■■■■■■■■■■■■■■■■")

            error_file_logger = utils.create_error_file_logger(motion, trace_model, replace_model, output_vmd_path)

            error_file_logger.warning("■■■■■■■■■■■■■■■■■")
            error_file_logger.warning("■　**WARNING**　")
            error_file_logger.warning("■　モーションに「親指０」が登録されており、変換先モデルに「親指０」がありません。")
            error_file_logger.warning("■　指位置合わせをスキップします。")
            error_file_logger.warning("■■■■■■■■■■■■■■■■■")

            return False
                
        print("■■ 手首位置合わせ補正 -----------------")

        # センターから手首までの位置(トレース先モデル)
        all_rep_wrist_links, _ = replace_model.create_link_2_top_lr("手首")

        # 肩から手首までのリンク生成(トレース先)
        arm_links = {
            "左": create_arm_links(replace_model, all_rep_wrist_links, "左"), 
            "右": create_arm_links(replace_model, all_rep_wrist_links, "右")
        }
        # logger.debug("left_arm_links: %s", [ x.name for x in arm_links["左"]])    
        
        target_bones = ["左腕", "左ひじ", "左手首", "右腕", "右ひじ", "右手首"]
        
        if is_floor_hand:
            target_bones.extend(["センター", "上半身"])

        # 事前準備
        prepare(motion, arm_links, hand_distance, is_floor_hand, target_bones)

        if hand_distance >= 0:
            # 手首位置合わせ処理実行
            is_error_outputed = exec_arm_ik(motion, trace_model, replace_model, output_vmd_path, hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, hand_floor_distance, leg_floor_distance, is_finger_ik, finger_distance, org_motion_frames, all_rep_wrist_links, arm_links, target_bones)

            # キー有効可否設定
            reset_activate(motion, arm_links, is_floor_hand)

            # 補間曲線再設定
            reset_complement(motion, arm_links, is_floor_hand)

            # 必要なキーだけ残す
            leave_valid_key_frames(motion, arm_links, is_floor_hand)

    return not is_error_outputed

# 必要なキーだけ残す
def leave_valid_key_frames(motion, arm_links, is_floor_hand):
    # 有効なキーのみのリストを再設定
    if "センター" in motion.frames:
        motion.frames["センター"] = [x for x in motion.frames["センター"] if x.key == True]
    
    if "上半身" in motion.frames:
        motion.frames["上半身"] = [x for x in motion.frames["上半身"] if x.key == True]

    for direction in ["左", "右"]:
        for al in arm_links[direction]:
            # 有効なキーのみのリストを再設定
            motion.frames[al.name] = [x for x in motion.frames[al.name] if x.key == True]

# 隣接有効キーを落とす
def reset_activate(motion, arm_links, is_floor_hand):
    if is_floor_hand:
        for link_name in ["センター", "上半身"]:
            if link_name in motion.frames:
                for bf_idx, bf in enumerate(motion.frames[link_name]):
                    if bf_idx > 0 and motion.frames[link_name][bf_idx - 1].key == True and bf.key == True and bf.read == False and bf.frame - motion.frames[link_name][bf_idx - 1].frame <= 1:
                        bf.key = False
    
    for direction in ["左", "右"]:
        for al in arm_links[direction]:
            for bf_idx, bf in enumerate(motion.frames[al.name]):
                if bf_idx > 0 and motion.frames[al.name][bf_idx - 1].key == True and bf.key == True and bf.read == False and bf.frame - motion.frames[al.name][bf_idx - 1].frame <= 2:
                    bf.key = False
                
                if bf_idx > 0 and bf_idx < len(motion.frames[al.name]) - 1 and motion.frames[al.name][bf_idx + 1].key == True and motion.frames[al.name][bf_idx + 1].read == True and bf.key == True and bf.read == False and motion.frames[al.name][bf_idx + 1].frame - bf.frame <= 2:
                    bf.key = False


# 腕IK調整後始末
def reset_complement(motion, arm_links, is_floor_hand):
    # 補間曲線を有効なキーだけに揃える
    
    # センター移動補間曲線
    if "センター" in motion.frames:
        for bf_idx, bf in enumerate(motion.frames["センター"]):
            reset_complement_frame(motion, "センター", bf_idx, utils.MX_x1_idxs, utils.MX_y1_idxs, utils.MX_x2_idxs, utils.MX_y2_idxs)
            reset_complement_frame(motion, "センター", bf_idx, utils.MY_x1_idxs, utils.MY_y1_idxs, utils.MY_x2_idxs, utils.MY_y2_idxs)
            reset_complement_frame(motion, "センター", bf_idx, utils.MZ_x1_idxs, utils.MZ_y1_idxs, utils.MZ_x2_idxs, utils.MZ_y2_idxs)

    # センターと上半身の回転補間曲線
    for link_name in ["センター", "上半身"]:
        if link_name in motion.frames:
            for bf_idx, bf in enumerate(motion.frames[link_name]):
                reset_complement_frame(motion, link_name, bf_idx, utils.R_x1_idxs, utils.R_y1_idxs, utils.R_x2_idxs, utils.R_y2_idxs)

        print("手首位置合わせ事後調整 b: %s" % link_name)
    
    for direction in ["左", "右"]:
        for al in arm_links[direction]:
            for bf_idx, bf in enumerate(motion.frames[al.name]):
                reset_complement_frame(motion, al.name, bf_idx, utils.R_x1_idxs, utils.R_y1_idxs, utils.R_x2_idxs, utils.R_y2_idxs)

            print("手首位置合わせ事後調整 b: %s" % al.name)


def reset_complement_frame(motion, link_name, bf_idx, x1_idxs, y1_idxs, x2_idxs, y2_idxs):
    now_bf = motion.frames[link_name][bf_idx]

    if now_bf.key == False or now_bf.read == True or now_bf.split_complement == True:
        # 現在キーが無効もしくは、読み込みキーか再分割追加キーの場合、処理スルー
        # logger.debug("処理スルー: %s, key: %s, read: %s", now_bf.frame, now_bf.key, now_bf.read)
        return

    # 前回のキー情報をクリア
    prev_bf = next_bf = None
    
    # 読み込んだ時か補間曲線分割で追加した次のキー
    for nbf_idx in range(bf_idx + 1, len(motion.frames[link_name])):
        if (motion.frames[link_name][nbf_idx].read == True or motion.frames[link_name][nbf_idx].split_complement == True) and motion.frames[link_name][nbf_idx].frame > now_bf.frame:
            next_bf = motion.frames[link_name][nbf_idx]
            break

    # 有効な前のキー
    for pbf_idx in range(bf_idx - 1, -1, -1):
        if motion.frames[link_name][pbf_idx].key == True and motion.frames[link_name][pbf_idx].frame < now_bf.frame:
            prev_bf = motion.frames[link_name][pbf_idx]
            break
    
    if prev_bf and next_bf:
        # 前後がある場合、補間曲線を分割する
        next_x1v = next_bf.complement[x1_idxs[3]]
        next_y1v = next_bf.complement[y1_idxs[3]]
        next_x2v = next_bf.complement[x2_idxs[3]]
        next_y2v = next_bf.complement[y2_idxs[3]]
        
        split_complement(motion, next_x1v, next_y1v, next_x2v, next_y2v, prev_bf, next_bf, now_bf, x1_idxs, y1_idxs, x2_idxs, y2_idxs, link_name, ",")


# キーの分割を再設定する
def recalc_bone_by_complement(motion, link_name, now, x1_idxs, y1_idxs, x2_idxs, y2_idxs):    
    for tbf_idx, tbf in enumerate(motion.frames[link_name]):
        if tbf.frame == now:
            # とりあえず登録対象のキーが既存なのでそのキーを有効にして返す
            # logger.debug(",追加のトコに既にキーあり,now, %s,%s", now,al.name)

            tbf.key = True
            # 再分割キー明示
            tbf.split_complement = True

            return tbf
        elif tbf.frame > now:
            # 対象のキーがなくて次に行ってしまった場合、挿入

            # 補間曲線込みでキーフレーム生成
            fill_bf = utils.calc_bone_by_complement(motion.frames, link_name, now, True)
            # 必ずキーは登録する
            fill_bf.key = True
            # 再分割キー明示
            fill_bf.split_complement = True
            # logger.debug("fill_bf f:%s, rotation: %s", fill_bf.frame, fill_bf.rotation.toEulerAngles())
            # 見つかった場所に挿入
            motion.frames[link_name].insert(tbf_idx, fill_bf)

            # 分割点のフレームを返す
            return fill_bf

    return None

# 補間曲線を分割する
def split_complement(motion, next_x1v, next_y1v, next_x2v, next_y2v, prev_bf, next_bf, now_bf, x1_idxs, y1_idxs, x2_idxs, y2_idxs, link_name, indent, resplit=True):
    # 区切りキー位置
    before_fill_bf = after_fill_bf = None

    # logger.debug("%s,【分割開始】: , %s, prev: %s, now: %s, next: %s, next_x1v: %s, next_y1v: %s, next_x2v: %s, next_y2v: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame, next_x1v, next_y1v, next_x2v, next_y2v)
    
    # ベジェ曲線を分割して新しい制御点を求める
    t, x, y, bresult, aresult, before_bz, after_bz = utils.calc_bezier_split(next_x1v, next_y1v, next_x2v, next_y2v, prev_bf.frame, next_bf.frame, now_bf.frame, link_name)

    # logger.debug(",%s, next_x1v: %s, next_y1v: %s, next_x2v: %s, next_y2v: %s, start: %s, now: %s, end: %s", indent, next_x1v, next_y1v, next_x2v, next_y2v, prev_bf.frame, now_bf.frame, next_bf.frame)
    # logger.debug(",%s, before_bz: %s", indent, before_bz)
    # logger.debug(",%s, after_bz: %s", indent, after_bz)

    # 分割（今回キー）の始点は、前半のB
    now_bf.complement[x1_idxs[0]] = now_bf.complement[x1_idxs[1]] = now_bf.complement[x1_idxs[2]] = now_bf.complement[x1_idxs[3]] = int(before_bz[1].x())
    now_bf.complement[y1_idxs[0]] = now_bf.complement[y1_idxs[1]] = now_bf.complement[y1_idxs[2]] = now_bf.complement[y1_idxs[3]] = int(before_bz[1].y())

    # 分割（今回キー）の終点は、後半のC
    now_bf.complement[x2_idxs[0]] = now_bf.complement[x2_idxs[1]] = now_bf.complement[x2_idxs[2]] = now_bf.complement[x2_idxs[3]] = int(before_bz[2].x())
    now_bf.complement[y2_idxs[0]] = now_bf.complement[y2_idxs[1]] = now_bf.complement[y2_idxs[2]] = now_bf.complement[y2_idxs[3]] = int(before_bz[2].y())

    # 次回読み込みキーの始点は、後半のB
    next_bf.complement[x1_idxs[0]] = next_bf.complement[x1_idxs[1]] = next_bf.complement[x1_idxs[2]] = next_bf.complement[x1_idxs[3]] = int(after_bz[1].x())
    next_bf.complement[y1_idxs[0]] = next_bf.complement[y1_idxs[1]] = next_bf.complement[y1_idxs[2]] = next_bf.complement[y1_idxs[3]] = int(after_bz[1].y())

    # 次回読み込みキーの終点は、後半のC
    next_bf.complement[x2_idxs[0]] = next_bf.complement[x2_idxs[1]] = next_bf.complement[x2_idxs[2]] = next_bf.complement[x2_idxs[3]] = int(after_bz[2].x())
    next_bf.complement[y2_idxs[0]] = next_bf.complement[y2_idxs[1]] = next_bf.complement[y2_idxs[2]] = next_bf.complement[y2_idxs[3]] = int(after_bz[2].y())

    if bresult and aresult:
        # logger.debug("%s, 【分割成功】: , %s,prev: %s, now: %s, next: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame)
        
        return
    else:
        # 分割に失敗している場合、さらに分割する

        if not bresult:
            # logger.debug("%s, 【分割前半失敗開始】: ,%s, prev: %s, now: %s, next: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame)

            # 前半用補間曲線
            next_x1v = now_bf.complement[x1_idxs[3]]
            next_y1v = now_bf.complement[y1_idxs[3]]
            next_x2v = now_bf.complement[x2_idxs[3]]
            next_y2v = now_bf.complement[y2_idxs[3]]

            # 前半を区切る位置を求める(t=0.5で曲線を半分に分割する位置)
            now, _ = utils.calc_interpolate_bezier_by_t(next_x1v, next_y1v, next_x2v, next_y2v, prev_bf.frame, now_bf.frame, 0.5)
            # logger.debug("%s, 【前半】, now: %s", indent, now)

            if now > prev_bf.frame:
                # ちゃんとキーが打てるような状態の場合、前半を再分割
                before_fill_bf = recalc_bone_by_complement(motion, link_name, now, x1_idxs, y1_idxs, x2_idxs, y2_idxs)

            if before_fill_bf:
                # 分割キーが取得できた場合、前半の補間曲線を分割して求めなおす
                split_complement(motion, next_x1v, next_y1v, next_x2v, next_y2v, prev_bf, now_bf, before_fill_bf, x1_idxs, y1_idxs, x2_idxs, y2_idxs, link_name, "{0},".format(indent))
            else:
                # 分割キーが取得できなかった場合、既にキーがあるので、さらに分割する

                # 分割キーが取得できなかった場合、念のため補間曲線を0-127の間に収め直す
                # 分割（今回キー）の始点は、前半のB
                r_x1 = 0 if 0 > before_bz[1].x() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < before_bz[1].x() else int(before_bz[1].x())
                now_bf.complement[x1_idxs[0]] = now_bf.complement[x1_idxs[1]] = now_bf.complement[x1_idxs[2]] = now_bf.complement[x1_idxs[3]] = r_x1
                r_y1 = 0 if 0 > before_bz[1].y() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < before_bz[1].y() else int(before_bz[1].y())
                now_bf.complement[y1_idxs[0]] = now_bf.complement[y1_idxs[1]] = now_bf.complement[y1_idxs[2]] = now_bf.complement[y1_idxs[3]] = r_y1

                # 分割（今回キー）の終点は、後半のC
                r_x2 = now_bf.complement[x2_idxs[3]] = 0 if 0 > before_bz[2].x() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < before_bz[2].x() else int(before_bz[2].x())
                now_bf.complement[x2_idxs[0]] = now_bf.complement[x2_idxs[1]] = now_bf.complement[x2_idxs[2]] = now_bf.complement[x2_idxs[3]] = r_x2
                r_y2 = 0 if 0 > before_bz[2].y() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < before_bz[2].y() else int(before_bz[2].y())
                now_bf.complement[y2_idxs[0]] = now_bf.complement[y2_idxs[1]] = now_bf.complement[y2_idxs[2]] = now_bf.complement[y2_idxs[3]] = r_y2

                # logger.debug("%s,前半分割キー取得失敗,R_x1_idxs,%s,R_y1_idxs,%s,R_x2_idxs,%s,R_y2_idxs,%s,before_bz,%s", indent, now_bf.complement[x1_idxs[3]], now_bf.complement[y1_idxs[3]], now_bf.complement[x2_idxs[3]], now_bf.complement[x2_idxs[3]],before_bz)

        if not aresult:
            # logger.debug("%s, 【分割後半失敗開始】: ,%s, prev: %s, now: %s, next: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame)

            # 後半用補間曲線
            next_x1v = next_bf.complement[x1_idxs[3]]
            next_y1v = next_bf.complement[y1_idxs[3]]
            next_x2v = next_bf.complement[x2_idxs[3]]
            next_y2v = next_bf.complement[y2_idxs[3]]

            # 後半を区切る位置を求める
            now, _ = utils.calc_interpolate_bezier_by_t(next_x1v, next_y1v, next_x2v, next_y2v, now_bf.frame, next_bf.frame, 0.5)
            # logger.debug("%s, 【後半】, now: %s", indent, now)

            if now > now_bf.frame:
                # ちゃんとキーが打てるような状態の場合、後半を再分割
                after_fill_bf = recalc_bone_by_complement(motion, link_name, now, x1_idxs, y1_idxs, x2_idxs, y2_idxs)

            if after_fill_bf:
                # 分割キーが取得できた場合、後半の補間曲線を分割して求めなおす
                split_complement(motion, next_x1v, next_y1v, next_x2v, next_y2v, now_bf, next_bf, after_fill_bf, x1_idxs, y1_idxs, x2_idxs, y2_idxs, link_name, "{0},".format(indent))
            else:
                # 分割キーが取得できなかった場合、念のため補間曲線を0-127の間に収め直す

                # 次回読み込みキーの始点は、後半のB
                r_x1 = 0 if 0 > after_bz[1].x() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < after_bz[1].x() else int(after_bz[1].x())
                next_bf.complement[x1_idxs[0]] = next_bf.complement[x1_idxs[1]] = next_bf.complement[x1_idxs[2]] = next_bf.complement[x1_idxs[3]] = r_x1
                r_y1 = 0 if 0 > after_bz[1].y() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < after_bz[1].y() else int(after_bz[1].y())
                next_bf.complement[y1_idxs[0]] = next_bf.complement[y1_idxs[1]] = next_bf.complement[y1_idxs[2]] = next_bf.complement[y1_idxs[3]] = r_y1

                # 次回読み込みキーの終点は、後半のC
                r_x2 = 0 if 0 > after_bz[2].x() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < after_bz[2].x() else int(after_bz[2].x())
                next_bf.complement[x2_idxs[0]] = next_bf.complement[x2_idxs[1]] = next_bf.complement[x2_idxs[2]] = next_bf.complement[x2_idxs[3]] = r_x2
                r_y2 = 0 if 0 > after_bz[2].y() else utils.COMPLEMENT_MMD_MAX if utils.COMPLEMENT_MMD_MAX < after_bz[2].y() else int(after_bz[2].y())
                next_bf.complement[y2_idxs[0]] = next_bf.complement[y2_idxs[1]] = next_bf.complement[y2_idxs[2]] = next_bf.complement[y2_idxs[3]] = r_y2

                # logger.debug("%s,後半分割キー取得失敗,R_x1_idxs,%s,R_y1_idxs,%s,R_x2_idxs,%s,R_y2_idxs,%s,after_bz,%s", indent, next_bf.complement[x1_idxs[3]], next_bf.complement[y1_idxs[3]], next_bf.complement[x2_idxs[3]], next_bf.complement[x2_idxs[3]],after_bz)

        # logger.debug("%s, 【分割失敗終了】: ,%s, prev: %s, now: %s, next: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame)
        return
    
    # logger.debug("%s, 【分割終了】: ,%s, prev: %s, now: %s, next: %s, next_x1v: %s, next_y1v: %s, next_x2v: %s, next_y2v: %s", indent, link_name, prev_bf.frame, now_bf.frame, next_bf.frame, next_x1v, next_y1v, next_x2v, next_y2v)
    return


# 腕IK調整事前準備
def prepare(motion, arm_links, hand_distance, is_floor_hand, target_bones):
    prev_log_cnt = 0

    for d in ["左", "右"]:
        for al in arm_links[d]:
            if not al.name in motion.frames:
                # キーがまったくない場合、とりあえず初期値で登録する
                # logger.debug("キー登録: %s" % al.name)
                motion.frames[al.name] = [utils.calc_bone_by_complement(motion.frames, al.name, 0)]

    for f in range(motion.last_motion_frame + 1):
        filled_bones = []

        for k in target_bones:
            if k in motion.frames:
                now_bfs = [(e, x) for e, x in enumerate(motion.frames[k]) if x.frame == f]

                if len(now_bfs) > 0:
                    bf = now_bfs[0][1]

                    # 該当フレームにどれかキーがある場合
                    for al_name in ["センター", "上半身"]:
                        # 床位置合わせONの場合、センターにキー追加
                        if al_name not in filled_bones and al_name in motion.frames:
                            logger.debug("センターprepare_fill_frame %s", bf.frame)
                            prepare_fill_frame(motion, al_name, bf, hand_distance)
                            filled_bones.append(al_name)

                    for direction in ["左", "右"]:
                        for al in arm_links[direction]:
                            if al.name in motion.frames and al.name not in filled_bones:
                                # 手首キーを埋める
                                prepare_fill_frame(motion, al.name, bf, hand_distance)
                                filled_bones.append(al.name)

                    if len(filled_bones) == len(target_bones):
                        # 両手が終わっててチェック済みならブレイク
                        break

            if len(filled_bones) == len(target_bones):
                # 両手が終わっててチェック済みならブレイク
                break
            
        if f // 500 > prev_log_cnt:
            print("手首位置合わせ事前調整 f: %s" % f)
            prev_log_cnt = f // 500

    print("手首位置合わせ事前調整終了")

def prepare_fill_frame(motion, link_name, bf, hand_distance):
    for tbf_idx, tbf in enumerate(motion.frames[link_name]):
        if tbf.frame == bf.frame:
            # とりあえず登録対象のキーが既存なので終了
            logger.debug("fill 既存あり: %s, i: %s, f: %s", link_name, tbf_idx, bf.frame)
            return link_name

        elif tbf.frame > bf.frame:
            # 対象のキーがなくて次に行ってしまった場合、挿入
            
            # 補間曲線込みでキーフレーム生成
            fillbf = utils.calc_bone_by_complement(motion.frames, link_name, bf.frame, True)
            # 手首間の距離がマイナスの場合（デバッグ機能）で有効
            # 普通の場合、とりあえず実際に登録はしない
            fillbf.key = True if hand_distance < 0 else False

            motion.frames[link_name].insert(tbf_idx, fillbf)
            logger.debug("fill insert: %s, i: %s, f: %s, key: %s: p: %s", link_name, tbf_idx, fillbf.frame, fillbf.key, fillbf.position)

            return link_name
    
    # 最後のフレームがなくてそのまま終了してしまった場合は、直前のキーを設定する
    fillbf = copy.deepcopy(tbf)
    # キーフレを現時点のに変える
    fillbf.frame = bf.frame
    # とりあえず実際に登録はしない
    fillbf.key = False
    # 読み込みキーではない
    fillbf.read = False
    logger.debug("fill 今回なし: %s, i: %s, f: %s", link_name, tbf_idx, fillbf.frame)
    motion.frames[link_name].append(fillbf)

    return link_name


# 手首位置合わせ実行
def exec_arm_ik(motion, trace_model, replace_model, output_vmd_path, hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, hand_floor_distance, leg_floor_distance, is_finger_ik, finger_distance, org_motion_frames, all_rep_wrist_links, arm_links, target_bones):    
    # 腕IKによる位置調整を行う場合

    # エラーを一度でも出力しているか(腕IK)
    is_error_outputed = False
    error_file_logger = None

    # 指の先までの位置(作成元モデル)
    all_org_finger_links, all_org_finger_indexes = trace_model.create_link_2_top_lr("人指３", "手首")
    # logger.debug("all_org_finger_links: %s", [ "{0}: {1}\n".format(x.name, x.position) for x in all_org_finger_links["左"]])    
    # logger.debug("all_org_finger_indexes: %s", [ x for x in all_org_finger_indexes["左"].keys()])    

    # 指の先までの位置(トレース先モデル)
    all_rep_finger_links, all_rep_finger_indexes = replace_model.create_link_2_top_lr("人指３", "手首")
    # logger.debug("all_rep_finger_links: %s", all_rep_finger_indexes["右"].keys())

    # 手首から指までのリンク生成(トレース先)
    finger_links = None
    if "左人指３" in replace_model.bones:
        # 指があるモデルのみ生成
        finger_links = {
            "左": create_finger_links(replace_model, all_rep_finger_links, "左"), 
            "右": create_finger_links(replace_model, all_rep_finger_links, "右")
        }
        # logger.debug("left_finger_links: %s", [ x.name for x in finger_links["左"]])    

    # 作成元モデルの手のひらの大きさ（手首から人指３までの長さ）
    org_palm_length = 1
    if "左人指３" in trace_model.bones and "左手首" in trace_model.bones:
        org_palm_length = (trace_model.bones["左手首"].position - trace_model.bones["左人指３"].position).length()
        print("作成元モデルの手の大きさ: %s" % org_palm_length)

    # # 変換先モデルの手のひらの大きさ（手首から人指３までの長さ）
    rep_palm_length = 1
    if "左人指３" in replace_model.bones and "左手首" in replace_model.bones:
        rep_palm_length = (replace_model.bones["左手首"].position - replace_model.bones["左人指３"].position).length()
        print("変換先モデルの手の大きさ: %s" % rep_palm_length)
    
    # 手のひらの大きさ差
    palm_diff_length = rep_palm_length / org_palm_length
    # logger.debug("palm_diff_length: %s", palm_diff_length)

    # 元モデルの上半身までのリンク生成
    org_upper_links, _ = trace_model.create_link_2_top_one( "上半身2", "上半身" )
    # logger.debug("org_upper_links: %s", org_upper_links)

    # 変換先モデルの上半身までのリンク生成
    rep_upper_links, _ = replace_model.create_link_2_top_one( "上半身2", "上半身" )

    # 腕の長さの差（始点：腕, 終点：手首）
    org_arm_length = (trace_model.bones["右手首"].position - trace_model.bones["右腕"].position).length()
    # logger.debug("org_arm_length: %s", org_arm_length)

    rep_arm_length = (replace_model.bones["右手首"].position - replace_model.bones["右腕"].position).length()
    # logger.debug("rep_arm_length: %s", rep_arm_length)

    # if rep_arm_length > org_arm_length:
    # arm_diff_length = (org_arm_length / rep_arm_length)
    # else:
    arm_diff_length = rep_arm_length / org_arm_length

    # 腕の長さと手の大きさで小さい方を採用
    arm_palm_diff_length = arm_diff_length if arm_diff_length < palm_diff_length else palm_diff_length

    # 比率が1以上の場合、とりあえず1で固定
    arm_palm_diff_length = 1 if arm_palm_diff_length > 1 else arm_palm_diff_length

    print("腕/手の長さ比率(上限1): %s" % arm_palm_diff_length)

    # 作成元モデルの手首の厚み
    org_wrist_thickness = trace_model.get_wrist_thickness_lr()
    # logger.debug("org_wrist_thickness: l: %s, r: %s", org_wrist_thickness["左"], org_wrist_thickness["右"])
    
    # 変換先モデルの手首の厚み
    rep_wrist_thickness = replace_model.get_wrist_thickness_lr()
    # logger.debug("rep_wrist_thickness: l: %s, r: %s", rep_wrist_thickness["左"], rep_wrist_thickness["右"])

    # 左右の手首の厚み
    if rep_wrist_thickness["左"] == 0 or org_wrist_thickness["左"] == 0 or rep_wrist_thickness["右"] == 0 or org_wrist_thickness["右"] == 0:
        print("手首の厚みが正常に測れなかったため、厚みを考慮できません。")
        # 手首の厚みが取得できなかった場合、0で固定
        wrist_thickness = {
            "左": 0,
            "右": 0
        }
    else:
        wrist_thickness = {
            "左": abs(rep_wrist_thickness["左"] - org_wrist_thickness["左"]) * arm_palm_diff_length,
            "右": abs(rep_wrist_thickness["右"] - org_wrist_thickness["右"]) * arm_palm_diff_length
        }

    print("手首の厚み差: l: %s, r: %s" % ( wrist_thickness["左"], wrist_thickness["右"]))
    
    # キーフレーム分割済みのフレーム情報を別保持
    org_fill_motion_frames = copy.deepcopy(motion.frames)

    if is_finger_ik:
        # 指位置合わせを行う場合

        # 元モデルの首までのリンク生成
        org_neck_links, _ = trace_model.create_link_2_top_one("首")
        # logger.debug("org_upper_links: %s", org_upper_links)

        # 変換先モデルの首までのリンク生成
        rep_neck_links, _ = replace_model.create_link_2_top_one("首")

        # 各指の先までの位置(作成元モデル)
        all_org_finger_links_list = {"左": [], "右": []}

        # 各指の先までの位置(変換先モデル)
        all_rep_finger_links_list = {"左": [], "右": []}

        for (finger_name, end_joint_name) in [("手首", ""), ("親指", "先"), ("人指", "先"), ("中指", "先"), ("薬指", "先"), ("小指", "先")]:
            end_joint_name = "{0}{1}".format(finger_name, end_joint_name)

            # 指から手首までのボーン構成
            oflinks, ofindexes = trace_model.create_link_2_top_lr(end_joint_name, "手首")

            left_finger_end_vertex = -1
            right_finger_end_vertex = -1
            if "指" in finger_name:
                left_finger_end_pos, left_finger_end_vertex = trace_model.get_finger_end_vertex("左", finger_name)
                oflinks["左"][0].position = left_finger_end_pos
                right_finger_end_pos, right_finger_end_vertex = trace_model.get_finger_end_vertex("右", finger_name)
                oflinks["右"][0].position = right_finger_end_pos

            all_org_finger_links_list["左"].append({"joint": end_joint_name, "links": oflinks["左"], "indexes": ofindexes["左"], "vertex": left_finger_end_vertex})
            all_org_finger_links_list["右"].append({"joint": end_joint_name, "links": oflinks["右"], "indexes": ofindexes["右"], "vertex": right_finger_end_vertex})
            
            rflinks, rfindexes = replace_model.create_link_2_top_lr(end_joint_name, "手首")

            left_finger_end_vertex = -1
            right_finger_end_vertex = -1
            if "指" in finger_name:
                left_finger_end_pos, left_finger_end_vertex = replace_model.get_finger_end_vertex("左", finger_name)
                rflinks["左"][0].position = left_finger_end_pos
                right_finger_end_pos, right_finger_end_vertex = replace_model.get_finger_end_vertex("右", finger_name)
                rflinks["右"][0].position = right_finger_end_pos

            all_rep_finger_links_list["左"].append({"joint": end_joint_name, "links": rflinks["左"], "indexes": rfindexes["左"], "vertex": left_finger_end_vertex})
            all_rep_finger_links_list["右"].append({"joint": end_joint_name, "links": rflinks["右"], "indexes": rfindexes["右"], "vertex": right_finger_end_vertex})

        for mdl_type, fll in zip(["作成元", "変換先"], [all_org_finger_links_list, all_rep_finger_links_list]):
            for direction in ["左", "右"]:
                print("{0}モデルの{1}指頂点INDEX: {2}".format(mdl_type, direction, ",".join(["{0}: {1}".format(l, x["vertex"]) for e, (l, x) in enumerate(zip(["首", "親", "人", "中", "薬", "小"], fll[direction])) if e > 0 ])))

        # # 親指の長さの差（始点：手首, 終点：親指２の先）
        # _, org_thumb_to_pos = utils.calc_tail_pos(trace_model, "右親指２")
        # org_thubm_finger_length = (trace_model.bones["右親指１"].position - org_thumb_to_pos).length()
        # # logger.debug("org_arm_length: %s", org_arm_length)

        # _, rep_thumb_to_pos = utils.calc_tail_pos(replace_model, "右親指２")
        # rep_thubm_finger_length = (replace_model.bones["右親指１"].position - rep_thumb_to_pos).length()
        # # logger.debug("rep_arm_length: %s", rep_arm_length)

        # # if rep_arm_length > org_arm_length:
        # # arm_diff_length = (org_arm_length / rep_arm_length)
        # # else:
        # thumb_finger_diff_length = (org_thubm_finger_length * arm_palm_diff_length) - rep_thubm_finger_length

        # print("親指の長さ差: %s" % thumb_finger_diff_length)

    if is_floor_hand:
        # # 足IKまでの位置(作成元モデル)
        # all_org_leg_ik_links, all_org_leg_ik_indexes = trace_model.create_link_2_top_lr("足ＩＫ")

        # 足までの位置(作成元モデル)
        all_org_leg_links, all_org_leg_indexes = trace_model.create_link_2_top_lr("足")
        # logger.debug("all_org_leg_links: %s", [ "{0}: {1}\n".format(x.name, x.position) for x in all_org_leg_links["左"]])    
        # logger.debug("all_org_leg_indexes: %s", [ x for x in all_org_leg_indexes["左"].keys()])    

        # 足までの位置(トレース先モデル)
        all_rep_leg_links, all_rep_leg_indexes = replace_model.create_link_2_top_lr("足")
        # logger.debug("all_rep_leg_links: %s", all_rep_leg_indexes["右"].keys())

        # # 足の厚み
        # org_leg_thickness_z = (all_org_leg_links["左"][0].position.z() + all_org_leg_links["右"][0].position.z()) / 2
        # rep_leg_thickness_z = (all_rep_leg_links["左"][0].position.z() + all_rep_leg_links["右"][0].position.z()) / 2
        
        # leg_thickness = rep_leg_thickness_z - org_leg_thickness_z
        # print("足の厚み: %s: 作成元: %s, 変換先: %s" % ( leg_thickness, org_leg_thickness_z, rep_leg_thickness_z ))

        # 背面の厚み
        org_back_thickness = 0
        org_back_vertex = None
        for al in (all_org_leg_links["左"] + all_org_leg_links["右"]):
            _, _, _, back_bone_below_pos, _, _, _, back_bone_below_vertex = trace_model.get_bone_vertex_position(al.name, al.position, trace_model.define_is_target_full_vertex(), True, True)
            if org_back_thickness < back_bone_below_pos.z():
                # より厚みのある頂点が取得できた場合、置き換え
                org_back_thickness = back_bone_below_pos.z()
                org_back_vertex = back_bone_below_vertex

        rep_back_thickness = 0
        rep_back_vertex = None
        for al in (all_rep_leg_links["左"] + all_rep_leg_links["右"]):
            _, _, _, back_bone_below_pos, _, _, _, back_bone_below_vertex = replace_model.get_bone_vertex_position(al.name, al.position, replace_model.define_is_target_full_vertex(), True, True)
            if rep_back_thickness < back_bone_below_pos.z():
                # より厚みのある頂点が取得できた場合、置き換え
                rep_back_thickness = back_bone_below_pos.z()
                rep_back_vertex = back_bone_below_vertex
        
        back_thickness = 0 if rep_back_thickness - org_back_thickness < 0 else rep_back_thickness - org_back_thickness

        print("背面の厚み(最小0): %s: 作成元: %s(%s), 変換先: %s(%s)" % ( back_thickness, org_back_thickness, org_back_vertex, rep_back_thickness, rep_back_vertex ))

        # 手首と上半身のリンク生成(トレース先)
        upper_links = {
            "左": create_upper_links(replace_model, all_rep_finger_links, "左"), 
            "右": create_upper_links(replace_model, all_rep_finger_links, "右")
        }

    # 直前のキー
    prev_bf = None
    # 空白を挟んだ直前のキー
    prev_space_bf = None
    for f in range(motion.last_motion_frame + 1):
        for k in target_bones:
            is_ik_adjust = False

            now_bfs = [(e, x) for e, x in enumerate(motion.frames[k]) if x.frame == f]
            if k in motion.frames and len(now_bfs) > 0:
                bf_idx = now_bfs[0][0]
                bf = now_bfs[0][1]

                if bf.key == True and bf.frame == f:
                    if prev_bf and bf.frame - prev_bf.frame >= 2:
                        # 直前キーがあり、かつ現在キーと2フレーム以上離れている場合、保持
                        prev_space_bf = prev_bf
                    
                    # 方向
                    org_direction = "左" if "左" in k else "右"
                    # 逆方向
                    reverse_org_direction = "右" if "左" in k else "左"
                    
                    # 元モデルのIK計算前指までの情報
                    # logger.debug("元モデルのIK計算前指までの情報")
                    # logger.debug("all_org_finger_links[org_direction]: %s(%s)", all_org_finger_links[org_direction][all_org_finger_indexes[org_direction]["肩"]], all_org_finger_indexes[org_direction]["肩"])
                    _, _, _, _, org_finger_global_3ds = utils.create_matrix_global(trace_model, all_org_finger_links[org_direction], org_motion_frames, bf, None)
                    if 0 <= bf.frame <= 20:
                        logger.debug("org_finger_global_3ds ------------------------")
                        for n in range(len(all_org_finger_links[org_direction])):
                            logger.debug("f: %s, org_finger_global_3ds %s, %s, %s", bf.frame, n, all_org_finger_links[org_direction][len(all_org_finger_links[org_direction]) - n - 1].name, org_finger_global_3ds[n])
                    # logger.debug("org 手首 index: %s", len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["手首"] - 1)
                    # logger.debug("元モデルの反対側の手の指までの情報")
                    # 元モデルの反対側の手の指までの情報
                    _, _, _, _, org_reverse_finger_global_3ds = utils.create_matrix_global(trace_model, all_org_finger_links[reverse_org_direction], org_motion_frames, bf, None)
                    if 0 <= bf.frame <= 20:
                        logger.debug("org_reverse_finger_global_3ds ------------------------")
                        for n in range(len(all_org_finger_links[reverse_org_direction])):
                            logger.debug("f: %s, org_reverse_finger_global_3ds %s, %s, %s", bf.frame, n, all_org_finger_links[reverse_org_direction][len(all_org_finger_links[reverse_org_direction]) - n - 1].name, org_reverse_finger_global_3ds[n])
                
                    # 変換先モデルのIK計算前指までの情報
                    _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)
                    # logger.debug("rep_finger_global_3ds ------------------------")
                    # for n in range(len(all_rep_finger_links[org_direction])):
                    #     logger.debug("f: %s, rep_finger_global_3ds %s, %s, %s", bf.frame, n, all_rep_finger_links[org_direction][len(all_rep_finger_links[org_direction]) - n - 1].name, rep_finger_global_3ds[n])
                    # 変換先モデルの反対側IK計算前指までの情報
                    _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)
                    # logger.debug("rep_reverse_finger_global_3ds ------------------------")
                    # for n in range(len(all_rep_finger_links[reverse_org_direction])):
                    #     logger.debug("f: %s, rep_reverse_finger_global_3ds %s, %s, %s", bf.frame, n, all_rep_finger_links[reverse_org_direction][len(all_rep_finger_links[reverse_org_direction]) - n - 1].name, rep_reverse_finger_global_3ds[n])

                    # logger.debug("d: %s", [org_direction, reverse_org_direction])

                    # logger.debug("all_org_finger_indexes[org_direction]: %s", all_org_finger_indexes[org_direction])
                    # logger.debug("org_wrist: %s", org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["手首"] - 1])
                    # # # logger.debug("all_org_finger_indexes: %s", [ "{0}\n".format(x) for x in org_finger_global_3ds])    
                    # logger.debug("reverse_wrist: %s", org_reverse_finger_global_3ds[len(org_reverse_finger_global_3ds) - all_org_finger_indexes[reverse_org_direction]["手首"] - 1])
                    # logger.debug("org_wrist_diff_3d: %s", (org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["手首"] - 1] - org_reverse_finger_global_3ds[len(org_reverse_finger_global_3ds) - all_org_finger_indexes[reverse_org_direction]["手首"] - 1]))

                    # 手首の距離
                    org_wrist_diff = (org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["手首"] - 1]).distanceToPoint(org_reverse_finger_global_3ds[len(org_reverse_finger_global_3ds) - all_org_finger_indexes[reverse_org_direction]["手首"] - 1])
                    # logger.debug("org_wrist_diff: %s", org_wrist_diff)

                    # 手首の距離
                    rep_wrist_diff = (rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1] - rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1]).length()
                    # logger.debug("rep_wrist_diff: %s", rep_wrist_diff)

                    # 手首間の距離
                    org_wrist_diff_rate = (org_wrist_diff / org_palm_length)

                    # 手首の距離が手のひらの大きさより大きいか(ハート型とかあるので、可変)
                    is_over_org_palm_length = hand_distance <= org_wrist_diff_rate

                    # logger.debug("org_wrist_diff_rate: %s, org_palm_length: %s, org_wrist_diff: %s", org_wrist_diff_rate, org_palm_length, org_wrist_diff)

                    if not is_finger_ik and not is_over_org_palm_length or hand_distance == 10:
                        for direction in [org_direction, reverse_org_direction]:
                            # 逆方向
                            reverse_direction = "右" if "左" == direction else "左"

                            # 手首が近接している場合のみ、腕IK処理実施
                            print("○手首近接あり: f: %s(%s), 境界: %s, 手首間の距離: %s" % (bf.frame, org_direction, hand_distance, org_wrist_diff_rate ))

                            # 元モデルの向いている回転量
                            org_upper_direction_qq = utils.calc_upper_direction_qq(trace_model, org_upper_links, org_motion_frames, bf)
                            # logger.debug("org_upper_direction_qq: %s", org_upper_direction_qq.toEulerAngles())

                            # 元モデルの向きを逆転させて、正面向きの位置を計算する
                            org_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_finger_global_3ds)
                            # 元モデルの向きを逆転させて、正面向きの位置を計算する(反対側)
                            org_reverse_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_reverse_finger_global_3ds)

                            # 元モデルの正面向き上半身の位置
                            org_front_upper_pos = org_front_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[direction]["上半身"] - 1]
                            # 元モデルの正面向き手首の位置
                            org_front_wrist_pos = org_front_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[direction]["手首"] - 1]
                            # 元モデルの正面向き手首の位置（反対側）
                            org_reverse_front_wrist_pos = org_reverse_front_finger_global_3ds[len(org_reverse_front_finger_global_3ds) - all_org_finger_indexes[reverse_direction]["手首"] - 1]

                            # 元モデルの正面向き指の位置
                            org_front_finger_pos = org_front_finger_global_3ds[len(org_front_finger_global_3ds) - all_org_finger_indexes[direction]["人指３"] - 1]
                            # 元モデルの正面向き指の位置(反対側)
                            org_reverse_front_finger_pos = org_reverse_front_finger_global_3ds[len(org_reverse_front_finger_global_3ds) - all_org_finger_indexes[reverse_direction]["人指３"] - 1]

                            # logger.debug("frame: %s, org_front_upper_pos before: %s", bf.frame, org_front_upper_pos)
                            # logger.debug("frame: %s, org_front_wrist_pos before: %s", bf.frame, org_front_wrist_pos)
                            # logger.debug("frame: %s, org_reverse_front_wrist_pos before: %s", bf.frame, org_reverse_front_wrist_pos)

                            # 変換先モデルの手首位置
                            rep_wrist_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["手首"] - 1]
                            # logger.debug("frame: %s, rep_wrist_pos before: %s", bf.frame, rep_wrist_pos)
                            # 変換先モデルの手首位置
                            rep_reverse_wrist_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_direction]["手首"] - 1]
                            # logger.debug("frame: %s, rep_reverse_wrist_pos before: %s", bf.frame, rep_reverse_wrist_pos)

                            # 変換先モデルの向いている回転量
                            rep_upper_direction_qq = utils.calc_upper_direction_qq(replace_model, rep_upper_links, motion.frames, bf)
                            # logger.debug("rep_upper_direction_qq: %s", rep_upper_direction_qq.toEulerAngles())

                            # 変換先モデルの向きを逆転させて、正面向きの手首の位置を計算する
                            rep_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_finger_global_3ds)
                            # 変換先モデルの向きを逆転させて、正面向きの手首の位置を計算する
                            rep_reverse_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_reverse_finger_global_3ds)

                            # 変換先モデルの正面向き上半身の位置
                            rep_front_upper_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["上半身"] - 1]
                            # 変換先モデルの正面向き手首の位置
                            rep_front_wrist_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["手首"] - 1]
                            # 変換先モデルの正面向き反対側手首の位置
                            rep_reverse_front_wrist_pos = rep_reverse_front_finger_global_3ds[len(rep_reverse_front_finger_global_3ds) - all_rep_finger_indexes[reverse_direction]["手首"] - 1]

                            # logger.debug("frame: %s, rep_front_upper_pos before: %s", bf.frame, rep_front_upper_pos)
                            # logger.debug("frame: %s, rep_front_wrist_pos before: %s", bf.frame, rep_front_wrist_pos)
                            # logger.debug("frame: %s, rep_reverse_front_wrist_pos before: %s", bf.frame, rep_reverse_front_wrist_pos)
                            
                            # logger.debug("org_front_upper_pos before: %s", org_front_upper_pos)
                            # logger.debug("org_front_wrist_pos before: %s", org_front_wrist_pos)
                            # logger.debug("org_reverse_front_wrist_pos before: %s", org_reverse_front_wrist_pos)
                            # logger.debug("rep_front_upper_pos before: %s", rep_front_upper_pos)
                            # logger.debug("rep_front_wrist_pos before: %s", rep_front_wrist_pos)
                            # logger.debug("rep_reverse_front_wrist_pos before: %s", rep_reverse_front_wrist_pos)

                            # 手首の位置を元モデルとだいたい同じ位置にする
                            # 1. 自分自身の上半身X位置
                            # 2: 元モデルの上半身と手首位置の差
                            rep_wrist_x = rep_front_upper_pos.x() \
                                + ( org_front_wrist_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length
                            rep_wrist_x_diff = rep_front_wrist_pos.x() - rep_wrist_x
                            # logger.debug("rep_wrist_x_diff: %s", rep_wrist_x_diff)
                            rep_front_wrist_pos.setX(rep_wrist_x)
                                                                        
                            # 手首の位置を元モデルとだいたい同じ位置にする(反対側)
                            rep_reverse_wrist_x = rep_front_upper_pos.x() \
                                + ( org_reverse_front_wrist_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length
                            rep_reverse_wrist_x_diff = rep_reverse_front_wrist_pos.x() - rep_reverse_wrist_x
                            # logger.debug("rep_reverse_wrist_x_diff: %s", rep_reverse_wrist_x_diff)
                            rep_reverse_front_wrist_pos.setX( rep_reverse_wrist_x )

                            # logger.debug("rep_front_wrist_pos x after: %s", rep_front_wrist_pos)
                            # logger.debug("rep_reverse_front_wrist_pos x after: %s", rep_reverse_front_wrist_pos)

                            # 手首の厚みを考慮
                            wrist_diff_sign = 1 if direction == "左" else -1
                            wrist_reverse_diff_sign = -1 if reverse_direction == "右" else 1
                            
                            if org_wrist_diff_rate < 0.5:
                                # 手のひらがピタッとくっついているような場合、手のひらの厚み補正
                                rep_front_wrist_pos.setX( rep_front_wrist_pos.x() + (wrist_thickness[direction] * wrist_diff_sign))
                                rep_reverse_front_wrist_pos.setX( rep_reverse_front_wrist_pos.x() + (wrist_thickness[reverse_direction] * wrist_reverse_diff_sign))

                            if arm_palm_diff_length >= 1 and org_wrist_diff_rate >= 1 \
                                and ((org_front_wrist_pos.x() <= org_front_finger_pos.x() <= org_reverse_front_wrist_pos.x() \
                                        and org_front_wrist_pos.x() <= org_reverse_front_finger_pos.x() <= org_reverse_front_wrist_pos.x()) \
                                    or (org_front_wrist_pos.x() >= org_front_finger_pos.x() >= org_reverse_front_wrist_pos.x() \
                                        and org_front_wrist_pos.x() >= org_reverse_front_finger_pos.x() >= org_reverse_front_wrist_pos.x())) :
                                # 変換先の方が大きくて、ある程度離れていて、かつ指が両手首の間にある場合、手の大きさを考慮する
                                # logger.debug("手の大きさを考慮: arm_palm_diff_length: %s, org_wrist_diff_rate: %s", arm_palm_diff_length, org_wrist_diff_rate)

                                # 元モデルの手首から指３までで最も手首から離れている距離
                                org_farer_finger_length = calc_farer_finger_length(org_front_finger_global_3ds, all_org_finger_indexes, direction)
                                # logger.debug("org_farer_finger_length: %s", org_farer_finger_length)

                                # 元モデルの手の大きさとの差
                                org_farer_finger_diff = org_palm_length - org_farer_finger_length
                                # logger.debug("org_farer_finger_diff: %s", org_farer_finger_diff)

                                # 元モデルの手首から指３までで最も手首から離れている距離（反対側）
                                org_reverse_farer_finger_length = calc_farer_finger_length(org_reverse_front_finger_global_3ds, all_org_finger_indexes, reverse_direction)
                                # logger.debug("org_farer_finger_length: %s", org_farer_finger_length)

                                # 元モデルの手の大きさとの差（反対側）
                                org_reverse_farer_finger_diff = org_palm_length - org_reverse_farer_finger_length
                                # logger.debug("org_reverse_farer_finger_diff: %s", org_reverse_farer_finger_diff)

                                # 手首から指３までで最も手首から離れている距離
                                rep_farer_finger_length = calc_farer_finger_length(rep_front_finger_global_3ds, all_rep_finger_indexes, direction)
                                # logger.debug("rep_farer_finger_length: %s", rep_farer_finger_length)

                                # 手の大きさとの差
                                rep_farer_finger_diff = rep_palm_length - rep_farer_finger_length
                                # logger.debug("rep_farer_finger_diff: %s", rep_farer_finger_diff)

                                # logger.debug("手の大きさ: %s", ( rep_farer_finger_diff - org_farer_finger_length ))

                                # 手首から指３までで最も手首から離れている距離
                                rep_reverse_farer_finger_length = calc_farer_finger_length(rep_reverse_front_finger_global_3ds, all_rep_finger_indexes, reverse_direction)
                                # logger.debug("rep_reverse_farer_finger_length: %s", rep_reverse_farer_finger_length)

                                # 手の大きさとの差
                                rep_reverse_farer_finger_diff = rep_palm_length - rep_reverse_farer_finger_length
                                # logger.debug("rep_reverse_farer_finger_diff: %s", rep_reverse_farer_finger_diff)

                                rep_front_wrist_pos.setX( rep_front_wrist_pos.x() \
                                    + ( rep_farer_finger_diff - org_farer_finger_diff ) / 2 * wrist_diff_sign
                                )

                                rep_reverse_front_wrist_pos.setX( rep_reverse_front_wrist_pos.x() \
                                    + ( rep_reverse_farer_finger_diff - org_reverse_farer_finger_diff ) / 2 * wrist_reverse_diff_sign
                                )

                            # logger.debug("frame: %s, rep_front_wrist_pos after: %s", bf.frame, rep_front_wrist_pos)
                            # logger.debug("frame: %s, rep_reverse_front_wrist_pos after: %s", bf.frame, rep_reverse_front_wrist_pos)

                            # 変換先モデルの向きを元に戻して、正面向きの手首を回転させた位置に合わせる
                            rep_wrist_pos = create_direction_pos(rep_upper_direction_qq, rep_front_wrist_pos)
                            # logger.debug("frame: %s, rep_wrist_pos after: %s", bf.frame, rep_wrist_pos)

                            # # ---------
                            # wrist_ik_bone = "{0}偽IK".format(direction)
                            # if not wrist_ik_bone in motion.frames:
                            #     motion.frames[wrist_ik_bone] = []
                            
                            # wikbf = VmdBoneFrame(bf.frame)
                            # wikbf.name = wrist_ik_bone.encode('shift-jis')
                            # wikbf.format_name = wrist_ik_bone
                            # wikbf.frame = bf.frame
                            # wikbf.key = True
                            # wikbf.position = rep_wrist_pos
                            # motion.frames[wrist_ik_bone].append(wikbf)
                            # # ---------

                            # 変換先モデルの向きを元に戻して、正面向きの手首を回転させた位置に合わせる(反対側)
                            rep_reverse_wrist_pos = create_direction_pos(rep_upper_direction_qq, rep_reverse_front_wrist_pos)
                            # logger.debug("frame: %s, rep_reverse_wrist_pos after: %s", bf.frame, rep_reverse_wrist_pos)

                            # # ---------
                            # reverse_wrist_ik_bone = "{0}偽IK".format(reverse_direction)
                            # if not reverse_wrist_ik_bone in motion.frames:
                            #     motion.frames[reverse_wrist_ik_bone] = []
                            
                            # rwikbf = VmdBoneFrame(bf.frame)
                            # rwikbf.name = reverse_wrist_ik_bone.encode('shift-jis')
                            # rwikbf.format_name = reverse_wrist_ik_bone
                            # rwikbf.frame = bf.frame
                            # rwikbf.key = True
                            # rwikbf.position = rep_reverse_wrist_pos
                            # motion.frames[reverse_wrist_ik_bone].append(rwikbf)
                            # # ---------

                            # 手首位置から角度を求める
                            calc_arm_IK2FK(rep_wrist_pos, replace_model, arm_links[direction], all_rep_wrist_links[direction], direction, motion.frames, bf, prev_space_bf)
                            # 反対側の手首位置から角度を求める
                            calc_arm_IK2FK(rep_reverse_wrist_pos, replace_model, arm_links[reverse_direction], all_rep_wrist_links[reverse_direction], reverse_direction, motion.frames, bf, prev_space_bf)

                            # 指位置調整-----------------

                            if finger_links and wrist_thickness["左"] != 0 and wrist_thickness["右"] != 0 and is_finger_ik == False:
                                # 指があるモデルの場合、手首角度調整。
                                # ただし、手首の厚みが取れなかった場合、ボーン構造が通常と異なる可能性があるため、調整対象外

                                # 手首の位置が変わっているので再算出

                                # 変換先モデルのIK計算前指までの情報
                                _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)
                                # logger.debug("rep_finger_global_3ds ------------------------")
                                # for n in range(len(all_rep_finger_links[org_direction])):
                                #     logger.debug("rep_finger_global_3ds %s, %s, %s", n, all_rep_finger_links[org_direction][len(all_rep_finger_links[org_direction]) - n - 1].name, rep_finger_global_3ds[n])
                                # 変換先モデルの反対側IK計算前指までの情報
                                _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)
                                # logger.debug("rep_reverse_finger_global_3ds ------------------------")
                                # for n in range(len(all_rep_finger_links[reverse_org_direction])):
                                #     logger.debug("rep_finger_global_3ds %s, %s, %s", n, all_rep_finger_links[reverse_org_direction][len(all_rep_finger_links[reverse_org_direction]) - n - 1].name, rep_reverse_finger_global_3ds[n])

                                # 変換先モデルの手首位置
                                rep_wrist_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["手首"] - 1]
                                # logger.debug("frame: %s, rep_wrist_pos before: %s", bf.frame, rep_wrist_pos)
                                # 変換先モデルの手首位置
                                rep_reverse_wrist_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_direction]["手首"] - 1]
                                # logger.debug("frame: %s, rep_reverse_wrist_pos before: %s", bf.frame, rep_reverse_wrist_pos)

                                # 変換先モデルの向いている回転量
                                rep_upper_direction_qq = utils.calc_upper_direction_qq(replace_model, rep_upper_links, motion.frames, bf)
                                # logger.debug("rep_upper_direction_qq: %s", rep_upper_direction_qq.toEulerAngles())

                                # 変換先モデルの向きを逆転させて、正面向きの手首の位置を計算する
                                rep_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_finger_global_3ds)
                                # 変換先モデルの向きを逆転させて、正面向きの手首の位置を計算する
                                rep_reverse_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_reverse_finger_global_3ds)

                                # # 変換先モデルの正面向き上半身の位置
                                # rep_front_upper_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["上半身"] - 1]
                                # 変換先モデルの正面向き手首の位置
                                rep_front_wrist_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[direction]["手首"] - 1]
                                # 変換先モデルの正面向き反対側手首の位置
                                rep_reverse_front_wrist_pos = rep_reverse_front_finger_global_3ds[len(rep_reverse_front_finger_global_3ds) - all_rep_finger_indexes[reverse_direction]["手首"] - 1]

                                # 変換先モデルの正面向き指３の位置
                                rep_front_finger_pos = rep_front_finger_global_3ds[len(rep_front_finger_global_3ds) - all_rep_finger_indexes[direction]["人指３"] - 1]
                                # 変換先モデルの正面向き指３の位置
                                rep_reverse_front_finger_pos = rep_reverse_front_finger_global_3ds[len(rep_reverse_front_finger_global_3ds) - all_rep_finger_indexes[reverse_direction]["人指３"] - 1]

                                # if (org_front_wrist_pos.x() <= org_front_finger_pos.x() <= org_reverse_front_wrist_pos.x() \
                                #     and org_front_wrist_pos.x() <= org_reverse_front_finger_pos.x() <= org_reverse_front_wrist_pos.x()) \
                                #     or (org_front_wrist_pos.x() >= org_front_finger_pos.x() >= org_reverse_front_wrist_pos.x() \
                                #     and org_front_wrist_pos.x() >= org_reverse_front_finger_pos.x() >= org_reverse_front_wrist_pos.x()) :
                                # logger.debug("指位置調整: ow: %s, of: %s, orf: %s, orw: %s", org_front_wrist_pos.x(), org_front_finger_pos.x(), org_reverse_front_finger_pos.x(), org_reverse_front_wrist_pos.x() )
                                    
                                # 指の位置を元モデルとだいたい同じ位置にする
                                # 1. 自分自身の上半身X位置
                                # 2: 元モデルの上半身と手首位置の差
                                rep_front_finger_pos.setX( rep_front_wrist_pos.x() \
                                    + (( org_front_finger_pos.x() - org_front_wrist_pos.x() ) * arm_palm_diff_length )
                                )
                                # logger.debug("(( org_front_finger_pos.x() - org_front_upper_pos.x() ) * arm_diff_length): %s", (( org_front_finger_pos.x() - org_front_upper_pos.x() ) * arm_diff_length))
                                    
                                # 指の位置を元モデルとだいたい同じ位置にする(反対側)
                                rep_reverse_front_finger_pos.setX( rep_reverse_front_wrist_pos.x() \
                                    + (( org_reverse_front_finger_pos.x() - org_reverse_front_wrist_pos.x() ) * arm_palm_diff_length)
                                )
                                # logger.debug("(( org_reverse_front_finger_pos.x() - org_front_upper_pos.x() )  * arm_diff_length): %s", (( org_reverse_front_finger_pos.x() - org_front_upper_pos.x() )  * arm_diff_length))

                                # 変換先モデルの向きを元に戻して、正面向きの指３を回転させた位置に合わせる
                                rep_finger_pos = create_direction_pos(rep_upper_direction_qq, rep_front_finger_pos)
                                # logger.debug("frame: %s, rep_finger_pos after: %s", bf.frame, rep_finger_pos)

                                # 変換先モデルの向きを元に戻して、正面向きの指３を回転させた位置に合わせる(反対側)
                                rep_reverse_finger_pos = create_direction_pos(rep_upper_direction_qq, rep_reverse_front_finger_pos)
                                # logger.debug("frame: %s, rep_reverse_finger_pos after: %s", bf.frame, rep_reverse_finger_pos)

                                # 指３位置から角度を求める
                                calc_arm_IK2FK(rep_finger_pos, replace_model, finger_links[direction], all_rep_finger_links[direction], direction, motion.frames, bf, prev_space_bf)
                                # 反対側の指３位置から角度を求める
                                calc_arm_IK2FK(rep_reverse_finger_pos, replace_model, finger_links[reverse_direction], all_rep_finger_links[reverse_direction], reverse_direction, motion.frames, bf, prev_space_bf)

                            break

                        # 手首位置合わせ結果判定 ------------

                        # logger.debug("bf: %s, 右腕: %s", bf.frame, motion.frames["左腕"][bf_idx].frame)

                        # d = QQuaternion.dotProduct(bf.rotation, org_bf.rotation)
                        # rk_name = bf.format_name.replace(direction, reverse_direction)
                        # logger.debug("bf.name: %s, bf_idx: %s, 右肩: %s", bf.format_name, bf_idx, len(motion.frames["右肩"]))
                        # lsd = abs(QQuaternion.dotProduct(motion.frames["左肩"][bf_idx].rotation, org_fill_motion_frames["左肩"][bf_idx].rotation))
                        # rsd = abs(QQuaternion.dotProduct(motion.frames["右肩"][bf_idx].rotation, org_fill_motion_frames["右肩"][bf_idx].rotation))
                        lad = abs(QQuaternion.dotProduct(motion.frames["左腕"][bf_idx].rotation, org_fill_motion_frames["左腕"][bf_idx].rotation))
                        rad = abs(QQuaternion.dotProduct(motion.frames["右腕"][bf_idx].rotation, org_fill_motion_frames["右腕"][bf_idx].rotation))
                        if lad < 0.85 or rad < 0.85:
                            print("%sフレーム目手首位置合わせ失敗: 手首間: %s, 左腕:%s, 右腕:%s" % (bf.frame, org_wrist_diff_rate, lad, rad))
                            # 失敗時のみエラーログ出力
                            if not is_error_outputed:
                                is_error_outputed = True
                                if not error_file_logger:
                                    error_file_logger = utils.create_error_file_logger(motion, trace_model, replace_model, output_vmd_path)

                                error_file_logger.info("作成元モデルの手の大きさ: %s", org_palm_length)
                                error_file_logger.info("変換先モデルの手の大きさ: %s", rep_palm_length)
                                error_file_logger.info("手首の厚み: l: %s, r: %s", wrist_thickness["左"], wrist_thickness["右"])
                                # error_file_logger.debug("作成元の上半身の厚み: %s", org_upper_thickness_diff)
                                # error_file_logger.debug("変換先の上半身の厚み: %s", rep_upper_thickness_diff)
                                # error_file_logger.debug("肩幅の差: %s" , showlder_diff_length)

                            error_file_logger.warning("%sフレーム目手首位置合わせ失敗: 手首間: %s, 左腕:%s, 右腕:%s" , bf.frame, org_wrist_diff_rate, lad, rad)
                        else:
                            # logger.debug("手首位置合わせ成功: f: %s, 左腕:%s, 右腕:%s", bf.frame, lad, rad)
                            pass

                        for dd in [direction, reverse_direction]:
                            # 指位置調整は実際には手首のみ角度調整で、arm_linksに含まれている
                            for al in arm_links[dd]:
                                # if is_finger_ik and "手首" in al.name:
                                #     # 指位置合わせの場合、手首は動かさない
                                #     continue

                                now_al_bf = [(e, x) for e, x in enumerate(motion.frames[al.name]) if x.frame == f][0]

                                if lad >= 0.85 and rad >= 0.85:
                                    # 角度調整が既定内である場合
                                    motion.frames[al.name][now_al_bf[0]].key = True

                                    # logger.debug("採用: cfk: %s, bf: %s, f: %s, read: %s, rot: %s", cfk, bf.frame, motion.frames[cfk][bf_idx].frame, motion.frames[cfk][bf_idx].read, motion.frames[cfk][bf_idx].rotation.toEulerAngles())
                                else:
                                    # 角度調整が既定外である場合、クリア
                                    past_al_bf = [(e, x) for e, x in enumerate(org_fill_motion_frames[al.name]) if x.frame == f][0]
                                    motion.frames[al.name][now_al_bf[0]] = copy.deepcopy(past_al_bf[1])
                                    # logger.debug("クリア: cfk: %s, bf_idx: %s, rot: %s", cfk, bf_idx, motion.frames[cfk][bf_idx].rotation.toEulerAngles())
                    else:
                        if not is_finger_ik and hand_distance <= org_wrist_diff_rate <= hand_distance * 2:
                            print("－手首近接なし: f: %s(%s), 境界: %s, 手首間の距離: %s" % (bf.frame, org_direction, hand_distance, org_wrist_diff_rate ))

                    if is_finger_ik:
                        # 最短距離
                        min_finger_distance = 99999999
                        # 最短の指（作成元正方向）
                        min_force_idx = -1
                        min_force_joint_name = None
                        min_force_direction = None
                        # 最短の指（作成元逆方向）
                        min_reverse_idx = -1
                        min_reverse_joint_name = None
                        min_reverse_direction = None

                        # 指位置合わせの場合、まず指位置の距離を測る
                        for _oidx, org_finger_links in enumerate(all_org_finger_links_list[org_direction]):
                            
                            # 元モデルのIK計算前指までの情報
                            _, _, _, _, org_finger_global_3ds = utils.create_matrix_global(trace_model, org_finger_links["links"], org_motion_frames, bf, None)

                            for _ridx, org_reverse_finger_links in enumerate(all_org_finger_links_list[reverse_org_direction]):
                                # 元モデルのIK計算前指までの情報
                                _, _, _, _, org_reverse_finger_global_3ds = utils.create_matrix_global(trace_model, org_reverse_finger_links["links"], org_motion_frames, bf, None)
                                
                                # 手首を含む指の距離を測る
                                end_finger_end_idx = org_finger_links["indexes"]["手首"] + 1
                                end_reverse_finger_end_idx = org_reverse_finger_links["indexes"]["手首"] + 1

                                for _ol_idx in range(0, end_finger_end_idx, 1):
                                    for _rl_idx in range(0, end_reverse_finger_end_idx, 1):
                                        
                                        now_org_finger_distance = org_finger_global_3ds[len(org_finger_global_3ds) - _ol_idx - 1].distanceToPoint(org_reverse_finger_global_3ds[len(org_reverse_finger_global_3ds) - _rl_idx - 1])
                                        if now_org_finger_distance < min_finger_distance:
                                            # 指の間が最短よりさらに短い場合、保持
                                            min_force_idx = _oidx
                                            min_force_joint_name = org_finger_links["links"][_ol_idx].name[1:]
                                            min_force_direction = org_direction
                                            min_reverse_idx = _ridx
                                            min_reverse_joint_name = org_reverse_finger_links["links"][_rl_idx].name[1:]
                                            min_reverse_direction = reverse_org_direction

                                            min_finger_distance = now_org_finger_distance
                        
                        if bf_idx == 0:
                            # 最初はとりあえず前回として保持
                            past_min_force_idx = min_force_idx
                            past_min_reverse_idx = min_reverse_idx
                            past_force_joint_name = min_force_joint_name
                            past_reverse_joint_name = min_reverse_joint_name
                            past_min_force_direction = min_force_direction
                            past_min_reverse_direction = min_reverse_direction
                            prev_finger_bf = bf

                        # 手首間の距離
                        org_finger_diff_rate = (min_finger_distance / org_palm_length)

                        # 指の距離が指定より大きいか
                        is_over_org_finger_length = finger_distance <= org_finger_diff_rate

                        if (not is_over_org_finger_length or finger_distance == 10):
                            is_prev_load = False
                            prev_load = ""
                            if bf_idx > 0 and bf.frame - prev_finger_bf.frame <= 2 and prev_finger_bf.key == True and "指" in past_force_joint_name and "指" in past_reverse_joint_name and "指" in min_force_joint_name and "指" in min_reverse_joint_name:
                                # 前と2F以下しか離れておらず、いずれも指の場合、前のを維持
                                min_force_idx = past_min_force_idx
                                min_reverse_idx = past_min_reverse_idx
                                min_force_joint_name = past_force_joint_name
                                min_reverse_joint_name = past_reverse_joint_name
                                min_force_direction = past_min_force_direction
                                min_reverse_direction = past_min_reverse_direction
                                is_prev_load = True
                                prev_load = " (前F引継)"

                            # 手首が近接している場合のみ、腕IK処理実施
                            print("○指近接あり: f: %s(%s%s:%s%s)%s, 境界: %s, 指先間の距離: %s" % (bf.frame, min_force_direction, min_force_joint_name, min_reverse_direction, min_reverse_joint_name, prev_load, finger_distance, org_finger_diff_rate ))

                            direction = min_force_direction
                            reverse_direction = min_reverse_direction

                            # 最接近の指の名前
                            force_joint_name = min_force_joint_name
                            reverse_joint_name = min_reverse_joint_name

                            # 最接近の指のリンク（作成元）
                            org_force_target_finger_links = all_org_finger_links_list[direction][min_force_idx]["links"]
                            org_force_target_finger_indexes = all_org_finger_links_list[direction][min_force_idx]["indexes"]
                            
                            # 最接近の反対側指のリンク（作成元）
                            org_reverse_target_finger_links = all_org_finger_links_list[reverse_direction][min_reverse_idx]["links"]
                            org_reverse_target_finger_indexes = all_org_finger_links_list[reverse_direction][min_reverse_idx]["indexes"]

                            # 最接近の指のリンク（変換先）
                            rep_force_target_finger_links = all_rep_finger_links_list[direction][min_force_idx]["links"]
                            rep_force_target_finger_indexes = all_rep_finger_links_list[direction][min_force_idx]["indexes"]
                            
                            # 最接近の反対側指のリンク（変換先）
                            rep_reverse_target_finger_links = all_rep_finger_links_list[reverse_direction][min_reverse_idx]["links"]
                            rep_reverse_target_finger_indexes = all_rep_finger_links_list[reverse_direction][min_reverse_idx]["indexes"]

                            # 腕から末端までのリンク生成
                            arm_finger_links = {
                                direction: create_arm_finger_links(replace_model, rep_force_target_finger_links, rep_force_target_finger_indexes, direction, force_joint_name), 
                                reverse_direction: create_arm_finger_links(replace_model, rep_reverse_target_finger_links, rep_reverse_target_finger_indexes, reverse_direction, reverse_joint_name)
                            }

                            # ----------------------

                            # 元モデルのIK計算前指までの情報
                            _, _, _, _, org_neck_global_3ds = utils.create_matrix_global(trace_model, org_neck_links, org_motion_frames, bf, None)
                            _, _, _, _, org_finger_global_3ds = utils.create_matrix_global(trace_model, org_force_target_finger_links, org_motion_frames, bf, None)
                            _, _, _, _, org_reverse_finger_global_3ds = utils.create_matrix_global(trace_model, org_reverse_target_finger_links, org_motion_frames, bf, None)


                            # 変換先モデルのIK計算前指までの情報
                            _, _, _, _, rep_neck_global_3ds = utils.create_matrix_global(replace_model, rep_neck_links, motion.frames, bf, None)
                            _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, rep_force_target_finger_links, motion.frames, bf, None)
                            _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, rep_reverse_target_finger_links, motion.frames, bf, None)

                            # ---------------------

                            # 元モデルの向いている回転量
                            org_upper_direction_qq = utils.calc_upper_direction_qq(trace_model, org_upper_links, org_motion_frames, bf)

                            # 元モデルの向きを逆転させて、正面向きの位置を計算する
                            org_front_neck_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_neck_global_3ds)
                            org_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_finger_global_3ds)
                            org_reverse_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_reverse_finger_global_3ds)

                            # 元モデルの正面向き上半身の位置
                            org_front_upper_pos = org_front_finger_global_3ds[len(org_front_finger_global_3ds) - org_force_target_finger_indexes["上半身"] - 1]
                            # 元モデルの正面向き首の位置
                            org_front_neck_pos = org_front_neck_global_3ds[-1]
                            # 元モデルの正面向き指の位置
                            org_front_finger_pos = org_front_finger_global_3ds[len(org_finger_global_3ds) - org_force_target_finger_indexes[force_joint_name] - 1]
                            # 元モデルの正面向き指の位置（反対側）
                            org_reverse_front_finger_pos = org_reverse_front_finger_global_3ds[len(org_reverse_front_finger_global_3ds) - org_reverse_target_finger_indexes[reverse_joint_name] - 1]

                            # 変換先モデルの指位置
                            rep_finger_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - rep_force_target_finger_indexes[force_joint_name] - 1]
                            # 変換先モデルの指位置
                            rep_reverse_finger_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - rep_reverse_target_finger_indexes[reverse_joint_name] - 1]

                            # 変換先モデルの向いている回転量
                            rep_upper_direction_qq = utils.calc_upper_direction_qq(replace_model, rep_upper_links, motion.frames, bf)

                            # 変換先モデルの向きを逆転させて、正面向きの指の位置を計算する
                            rep_front_neck_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_neck_global_3ds)
                            rep_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_finger_global_3ds)
                            rep_reverse_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_reverse_finger_global_3ds)

                            # 変換先モデルの正面向き上半身の位置
                            rep_front_upper_pos = rep_front_finger_global_3ds[len(rep_front_finger_global_3ds) - rep_force_target_finger_indexes["上半身"] - 1]
                            # 変換先モデルの正面向き上半身の位置
                            rep_front_neck_pos = rep_front_neck_global_3ds[-1]
                            # 変換先モデルの正面向き指の位置
                            rep_front_finger_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - rep_force_target_finger_indexes[force_joint_name] - 1]
                            # 変換先モデルの正面向き反対側指の位置
                            rep_reverse_front_finger_pos = rep_reverse_front_finger_global_3ds[len(rep_reverse_front_finger_global_3ds) - rep_reverse_target_finger_indexes[reverse_joint_name] - 1]

                            # -----------------

                            # 指の位置を元モデルとだいたい同じ位置にする
                            # 1. 自分自身の上半身X位置
                            # 2: 元モデルの上半身と指位置の差
                            rep_finger_x = rep_front_upper_pos.x() \
                                + (( org_front_finger_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length)
                            rep_front_finger_pos.setX(rep_finger_x)

                            # 指の位置を元モデルとだいたい同じ位置にする(反対側)
                            rep_reverse_finger_x = rep_front_upper_pos.x() \
                                + (( org_reverse_front_finger_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length)
                            rep_reverse_front_finger_pos.setX( rep_reverse_finger_x )
                                
                            # 指の位置を元モデルとだいたい同じ位置にする(Y)
                            if org_front_finger_pos.y() <= org_front_upper_pos.y():
                                # 上半身より下の場合は上半身基準
                                rep_finger_y = rep_front_upper_pos.y() \
                                        + (( org_front_finger_pos.y() - org_front_upper_pos.y() ) * arm_palm_diff_length)
                                rep_reverse_finger_y = rep_front_upper_pos.y() \
                                        + (( org_reverse_front_finger_pos.y() - org_front_upper_pos.y() ) * arm_palm_diff_length)
                            elif org_front_finger_pos.y() >= org_front_neck_pos.y():
                                # 首より上の場合は首基準
                                rep_finger_y = rep_front_neck_pos.y() \
                                        + (( org_front_finger_pos.y() - org_front_neck_pos.y() ) * arm_palm_diff_length)
                                rep_reverse_finger_y = rep_front_neck_pos.y() \
                                    + (( org_reverse_front_finger_pos.y() - org_front_neck_pos.y() ) * arm_palm_diff_length)
                            else:
                                # 間は中間くらい
                                rep_finger_y = (rep_front_upper_pos.y() + (rep_front_neck_pos.y() - rep_front_upper_pos.y()) /2) \
                                    + (( org_front_finger_pos.y() - (org_front_upper_pos.y() + (org_front_neck_pos.y() - org_front_upper_pos.y()) /2) ) * arm_palm_diff_length)
                                rep_front_finger_pos.setY(rep_finger_y)
                                rep_reverse_finger_y = (rep_front_upper_pos.y() + (rep_front_neck_pos.y() - rep_front_upper_pos.y()) /2) \
                                    + (( org_reverse_front_finger_pos.y() - (org_front_upper_pos.y() + (org_front_neck_pos.y() - org_front_upper_pos.y()) /2) ) * arm_palm_diff_length)
                            
                            rep_front_finger_pos.setY(rep_finger_y)
                            rep_reverse_front_finger_pos.setY( rep_reverse_finger_y )

                            # 基準となるZ位置(身体に遠い方のZ)
                            if not is_prev_load:
                                org_base_z = min(org_front_finger_pos.z(), org_reverse_front_finger_pos.z())
                                rep_base_z = min(rep_front_finger_pos.z(), rep_reverse_front_finger_pos.z())

                            rep_force_finger_z = rep_base_z \
                                    + ((org_front_finger_pos.z() - org_base_z) * arm_palm_diff_length)
                            rep_front_finger_pos.setZ( rep_force_finger_z )

                            rep_reverse_finger_z = rep_base_z \
                                    + ((org_reverse_front_finger_pos.z() - org_base_z) * arm_palm_diff_length)
                            rep_reverse_front_finger_pos.setZ( rep_reverse_finger_z )

                            # 変換先モデルの向きを元に戻して、正面向きの指を回転させた位置に合わせる
                            rep_finger_pos = create_direction_pos(rep_upper_direction_qq, rep_front_finger_pos)
                            # logger.debug("frame: %s, rep_finger_pos after: %s", bf.frame, rep_finger_pos)

                            # 変換先モデルの向きを元に戻して、正面向きの指を回転させた位置に合わせる(反対側)
                            rep_reverse_finger_pos = create_direction_pos(rep_upper_direction_qq, rep_reverse_front_finger_pos)
                            # logger.debug("frame: %s, rep_reverse_finger_pos after: %s", bf.frame, rep_reverse_finger_pos)

                            # 指位置から角度を求める
                            calc_arm_IK2FK(rep_finger_pos, replace_model, arm_finger_links[direction], rep_force_target_finger_links, direction, motion.frames, bf, prev_space_bf)
                            # 反対側の指位置から角度を求める
                            calc_arm_IK2FK(rep_reverse_finger_pos, replace_model, arm_finger_links[reverse_direction], rep_reverse_target_finger_links, reverse_direction, motion.frames, bf, prev_space_bf)

                            # # ---------
                            # finger_ik_bone = "{0}偽IK".format(direction)
                            # if not finger_ik_bone in motion.frames:
                            #     motion.frames[finger_ik_bone] = []
                            
                            # wikbf = VmdBoneFrame(bf.frame)
                            # wikbf.name = finger_ik_bone.encode('shift-jis')
                            # wikbf.format_name = finger_ik_bone
                            # wikbf.frame = bf.frame
                            # wikbf.key = True
                            # wikbf.position = rep_finger_pos
                            # motion.frames[finger_ik_bone].append(wikbf)
                            # # ---------

                            # # ---------
                            # reverse_finger_ik_bone = "{0}偽IK".format(reverse_direction)
                            # if not reverse_finger_ik_bone in motion.frames:
                            #     motion.frames[reverse_finger_ik_bone] = []
                            
                            # rwikbf = VmdBoneFrame(bf.frame)
                            # rwikbf.name = reverse_finger_ik_bone.encode('shift-jis')
                            # rwikbf.format_name = reverse_finger_ik_bone
                            # rwikbf.frame = bf.frame
                            # rwikbf.key = True
                            # rwikbf.position = rep_reverse_finger_pos
                            # motion.frames[reverse_finger_ik_bone].append(rwikbf)
                            # # ---------

                            # ----------------------

                            # 元モデルのIK計算前手首までの情報
                            _, _, _, _, org_finger_global_3ds = utils.create_matrix_global(trace_model, org_force_target_finger_links, org_motion_frames, bf, None)
                            _, _, _, _, org_reverse_finger_global_3ds = utils.create_matrix_global(trace_model, org_reverse_target_finger_links, org_motion_frames, bf, None)


                            # 変換先モデルのIK計算前手首までの情報
                            _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, rep_force_target_finger_links, motion.frames, bf, None)
                            _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, rep_reverse_target_finger_links, motion.frames, bf, None)

                            # ---------------------

                            # 元モデルの向きを逆転させて、正面向きの位置を計算する
                            org_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_finger_global_3ds)
                            org_reverse_front_finger_global_3ds = create_direction_pos_all(org_upper_direction_qq.inverted(), org_reverse_finger_global_3ds)

                            # 元モデルの正面向き手首の位置
                            org_front_wrist_pos = org_front_finger_global_3ds[len(org_finger_global_3ds) - org_force_target_finger_indexes["手首"] - 1]
                            # 元モデルの正面向き手首の位置（反対側）
                            org_reverse_front_wrist_pos = org_reverse_front_finger_global_3ds[len(org_reverse_front_finger_global_3ds) - org_reverse_target_finger_indexes["手首"] - 1]

                            # 変換先モデルの手首位置
                            rep_wrist_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - rep_force_target_finger_indexes["手首"] - 1]
                            # 変換先モデルの手首位置
                            rep_reverse_wrist_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - rep_reverse_target_finger_indexes["手首"] - 1]

                            rep_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_finger_global_3ds)
                            rep_reverse_front_finger_global_3ds = create_direction_pos_all(rep_upper_direction_qq.inverted(), rep_reverse_finger_global_3ds)

                            # 変換先モデルの正面向き手首の位置
                            rep_front_wrist_pos = rep_front_finger_global_3ds[len(rep_finger_global_3ds) - rep_force_target_finger_indexes["手首"] - 1]
                            # 変換先モデルの正面向き反対側手首の位置
                            rep_reverse_front_wrist_pos = rep_reverse_front_finger_global_3ds[len(rep_reverse_front_finger_global_3ds) - rep_reverse_target_finger_indexes["手首"] - 1]

                            # --------------------

                            # 手首の差
                            org_wrist_diff = abs( org_front_wrist_pos.x() - org_reverse_front_wrist_pos.x() ) * arm_palm_diff_length * 0.8
                            rep_wrist_diff = abs( rep_front_wrist_pos.x() - rep_reverse_front_wrist_pos.x() )

                            if rep_wrist_diff < org_wrist_diff:
                                # 手首位置が元々より狭い場合、手首の角度を考慮する

                                # ----------------
                                # 手首位置合わせ

                                # 手首の位置を元モデルとだいたい同じ位置にする
                                # 1. 自分自身の上半身X位置
                                # 2: 元モデルの上半身と手首位置の差
                                rep_wrist_x = rep_front_upper_pos.x() \
                                    + (( org_front_wrist_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length)
                                rep_front_wrist_pos.setX(rep_wrist_x)

                                # 手首の位置を元モデルとだいたい同じ位置にする(反対側)
                                rep_reverse_wrist_x = rep_front_upper_pos.x() \
                                    + (( org_reverse_front_wrist_pos.x() - org_front_upper_pos.x() ) * arm_palm_diff_length)
                                rep_reverse_front_wrist_pos.setX( rep_reverse_wrist_x )

                                # 指の位置を元モデルとだいたい同じ位置にする(Y)
                                if org_front_wrist_pos.y() <= org_front_upper_pos.y():
                                    # 上半身より下の場合は上半身基準
                                    rep_wrist_y = rep_front_upper_pos.y() \
                                            + (( org_front_wrist_pos.y() - org_front_upper_pos.y() ) * arm_palm_diff_length)
                                    rep_reverse_wrist_y = rep_front_upper_pos.y() \
                                            + (( org_reverse_front_wrist_pos.y() - org_front_upper_pos.y() ) * arm_palm_diff_length)
                                elif org_front_wrist_pos.y() >= org_front_neck_pos.y():
                                    # 首より上の場合は首基準
                                    rep_wrist_y = rep_front_neck_pos.y() \
                                            + (( org_front_wrist_pos.y() - org_front_neck_pos.y() ) * arm_palm_diff_length)
                                    rep_reverse_wrist_y = rep_front_neck_pos.y() \
                                        + (( org_reverse_front_wrist_pos.y() - org_front_neck_pos.y() ) * arm_palm_diff_length)
                                else:
                                    # 間は中間くらい
                                    rep_wrist_y = (rep_front_upper_pos.y() + (rep_front_neck_pos.y() - rep_front_upper_pos.y()) /2) \
                                        + (( org_front_wrist_pos.y() - (org_front_upper_pos.y() + (org_front_neck_pos.y() - org_front_upper_pos.y()) /2) ) * arm_palm_diff_length)
                                    rep_front_wrist_pos.setY(rep_wrist_y)
                                    rep_reverse_wrist_y = (rep_front_upper_pos.y() + (rep_front_neck_pos.y() - rep_front_upper_pos.y()) /2) \
                                        + (( org_reverse_front_wrist_pos.y() - (org_front_upper_pos.y() + (org_front_neck_pos.y() - org_front_upper_pos.y()) /2) ) * arm_palm_diff_length)
                                
                                if not is_prev_load:
                                    # 基準となるZ位置(身体に遠い方のZ)
                                    org_base_z = min(org_front_wrist_pos.z(), org_reverse_front_wrist_pos.z())
                                    rep_base_z = min(rep_front_wrist_pos.z(), rep_reverse_front_wrist_pos.z())

                                rep_force_wrist_z = rep_base_z \
                                        + ((org_front_wrist_pos.z() - org_base_z) * arm_palm_diff_length)
                                rep_front_wrist_pos.setZ( rep_force_wrist_z )

                                rep_reverse_wrist_z = rep_base_z \
                                        + ((org_reverse_front_wrist_pos.z() - org_base_z) * arm_palm_diff_length)
                                rep_reverse_front_wrist_pos.setZ( rep_reverse_wrist_z )

                                # 変換先モデルの向きを元に戻して、正面向きの手首を回転させた位置に合わせる
                                rep_wrist_pos = create_direction_pos(rep_upper_direction_qq, rep_front_wrist_pos)
                                # logger.debug("frame: %s, rep_wrist_pos after: %s", bf.frame, rep_wrist_pos)

                                # 変換先モデルの向きを元に戻して、正面向きの手首を回転させた位置に合わせる(反対側)
                                rep_reverse_wrist_pos = create_direction_pos(rep_upper_direction_qq, rep_reverse_front_wrist_pos)
                                # logger.debug("frame: %s, rep_reverse_wrist_pos after: %s", bf.frame, rep_reverse_wrist_pos)

                                # 手首位置から角度を求める
                                calc_arm_IK2FK(rep_wrist_pos, replace_model, arm_links[direction], rep_force_target_finger_links, direction, motion.frames, bf, prev_space_bf)
                                # 反対側の手首位置から角度を求める
                                calc_arm_IK2FK(rep_reverse_wrist_pos, replace_model, arm_links[reverse_direction], rep_reverse_target_finger_links, reverse_direction, motion.frames, bf, prev_space_bf)

                                # # ---------
                                # finger_ik_bone = "{0}偽IK2".format(direction)
                                # if not finger_ik_bone in motion.frames:
                                #     motion.frames[finger_ik_bone] = []
                                
                                # wikbf = VmdBoneFrame(bf.frame)
                                # wikbf.name = finger_ik_bone.encode('shift-jis')
                                # wikbf.format_name = finger_ik_bone
                                # wikbf.frame = bf.frame
                                # wikbf.key = True
                                # wikbf.position = rep_wrist_pos
                                # motion.frames[finger_ik_bone].append(wikbf)
                                # # ---------

                                # # ---------
                                # reverse_finger_ik_bone = "{0}偽IK2".format(reverse_direction)
                                # if not reverse_finger_ik_bone in motion.frames:
                                #     motion.frames[reverse_finger_ik_bone] = []
                                
                                # rwikbf = VmdBoneFrame(bf.frame)
                                # rwikbf.name = reverse_finger_ik_bone.encode('shift-jis')
                                # rwikbf.format_name = reverse_finger_ik_bone
                                # rwikbf.frame = bf.frame
                                # rwikbf.key = True
                                # rwikbf.position = rep_reverse_wrist_pos
                                # motion.frames[reverse_finger_ik_bone].append(rwikbf)
                                # # ---------

                                # 腕から末端までのリンク生成(手首あり)
                                arm_finger_links = {
                                    direction: create_arm_finger_links(replace_model, rep_force_target_finger_links, rep_force_target_finger_indexes, direction, force_joint_name, True), 
                                    reverse_direction: create_arm_finger_links(replace_model, rep_reverse_target_finger_links, rep_reverse_target_finger_indexes, reverse_direction, reverse_joint_name, True)
                                }

                                # 指位置から角度を求める
                                calc_arm_IK2FK(rep_finger_pos, replace_model, arm_finger_links[direction], rep_force_target_finger_links, direction, motion.frames, bf, prev_space_bf)
                                # 反対側の指位置から角度を求める
                                calc_arm_IK2FK(rep_reverse_finger_pos, replace_model, arm_finger_links[reverse_direction], rep_reverse_target_finger_links, reverse_direction, motion.frames, bf, prev_space_bf)

                                print("※手首角度調整追加: f: %s, 元: %s, 先: %s" % (bf.frame, org_wrist_diff, rep_wrist_diff ))
                            # else:
                            #     print("×手首角度調整なし: f: %s, %s: %s, %s: %s" % (bf.frame, direction, (rep_force_wrist_diff - org_force_wrist_diff), reverse_direction, (rep_reverse_wrist_diff - org_reverse_wrist_diff) ))
                            #     pass

                            # 指位置合わせ結果判定 ------------

                            lad = abs(QQuaternion.dotProduct(motion.frames["左腕"][bf_idx].rotation, org_fill_motion_frames["左腕"][bf_idx].rotation))
                            rad = abs(QQuaternion.dotProduct(motion.frames["右腕"][bf_idx].rotation, org_fill_motion_frames["右腕"][bf_idx].rotation))
                            if lad < 0.85 or rad < 0.85:
                                print("%sフレーム目指位置合わせ失敗: 指先間: %s, 左腕:%s, 右腕:%s" % (bf.frame, org_finger_diff_rate, lad, rad))
                                # 失敗時のみエラーログ出力
                                if not is_error_outputed:
                                    is_error_outputed = True
                                    if not error_file_logger:
                                        error_file_logger = utils.create_error_file_logger(motion, trace_model, replace_model, output_vmd_path)

                                    error_file_logger.info("作成元モデルの手の大きさ: %s", org_palm_length)
                                    error_file_logger.info("変換先モデルの手の大きさ: %s", rep_palm_length)
                                    error_file_logger.info("指の厚み: l: %s, r: %s", wrist_thickness["左"], wrist_thickness["右"])
                                    # error_file_logger.debug("作成元の上半身の厚み: %s", org_neck_thickness_diff)
                                    # error_file_logger.debug("変換先の上半身の厚み: %s", rep_neck_thickness_diff)
                                    # error_file_logger.debug("肩幅の差: %s" , showlder_diff_length)

                                error_file_logger.warning("%sフレーム目指位置合わせ失敗: 指先間: %s, 左腕:%s, 右腕:%s" , bf.frame, org_finger_diff_rate, lad, rad)
                            else:
                                # logger.debug("指位置合わせ成功: f: %s, 左腕:%s, 右腕:%s", bf.frame, lad, rad)
                                pass

                            for dd in [direction, reverse_direction]:
                                for al in arm_finger_links[dd]:
                                    if "指" not in al.name:
                                        now_al_bf = [(e, x) for e, x in enumerate(motion.frames[al.name]) if x.frame == f][0]
                                        if lad >= 0.85 and rad >= 0.85:
                                            # 角度調整が既定内である場合
                                            motion.frames[al.name][now_al_bf[0]].key = True

                                            # 前回INDEXとして保持
                                            past_min_force_idx = min_force_idx
                                            past_min_reverse_idx = min_reverse_idx
                                            past_force_joint_name = min_force_joint_name
                                            past_reverse_joint_name = min_reverse_joint_name
                                            past_min_force_direction = min_force_direction
                                            past_min_reverse_direction = min_reverse_direction
                                            prev_finger_bf = now_al_bf[1]

                                            # logger.debug("採用: cfk: %s, bf: %s, f: %s, read: %s, rot: %s", cfk, bf.frame, motion.frames[cfk][bf_idx].frame, motion.frames[cfk][bf_idx].read, motion.frames[cfk][bf_idx].rotation.toEulerAngles())
                                        else:
                                            # 角度調整が既定外である場合、クリア
                                            past_al_bf = [(e, x) for e, x in enumerate(org_fill_motion_frames[al.name]) if x.frame == f][0]
                                            motion.frames[al.name][now_al_bf[0]] = copy.deepcopy(past_al_bf[1])
                                            # logger.debug("クリア: cfk: %s, bf_idx: %s, rot: %s", cfk, bf_idx, motion.frames[cfk][bf_idx].rotation.toEulerAngles())     
                                                    
                        else:
                            if finger_distance <= org_finger_diff_rate <= finger_distance * 2:
                                print("－指近接なし: f: %s(%s), 境界: %s, 指先間の距離: %s" % (bf.frame, org_direction, finger_distance, org_finger_diff_rate ))
                    
                    # logger.debug("bf_idx: %s, cf:%s", bf_idx, motion.frames["センター"][bf_idx].frame)

                    if is_floor_hand:
                        # 上半身のY位置
                        org_upper_y = org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["上半身"] - 1].y()
                        # 元モデルの向いている回転量
                        org_upper_direction_qq = utils.calc_upper_direction_qq(trace_model, org_upper_links, org_motion_frames, bf)

                        # 手首のY位置
                        org_wrist_y = org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["手首"] - 1].y()
                        org_reverse_wrist_y = org_reverse_finger_global_3ds[len(org_reverse_finger_global_3ds) - all_org_finger_indexes[reverse_org_direction]["手首"] - 1].y()

                        # 足のY位置                            
                        # 元モデルのIK計算前足までの情報
                        _, _, _, _, org_leg_global_3ds = utils.create_matrix_global(trace_model, all_org_leg_links[org_direction], org_motion_frames, bf, None)
                        # 元モデルの反対側の足までの情報
                        _, _, _, _, org_reverse_leg_global_3ds = utils.create_matrix_global(trace_model, all_org_leg_links[reverse_org_direction], org_motion_frames, bf, None)

                        # 足のY位置
                        org_leg_y = org_leg_global_3ds[len(org_leg_global_3ds) - all_org_leg_indexes[org_direction]["足"] - 1].y()
                        org_reverse_leg_y = org_reverse_leg_global_3ds[len(org_reverse_leg_global_3ds) - all_org_leg_indexes[reverse_org_direction]["足"] - 1].y()

                        logger.debug("--------------")
                        logger.debug("%s hand_floor: p: %s, wy: %s, wyr: %s, ly: %s, lyr: %s", bf.frame, org_palm_length, org_wrist_y, org_reverse_wrist_y, org_leg_y, org_reverse_leg_y)

                        if (org_wrist_y <= org_palm_length * hand_floor_distance or org_reverse_wrist_y <= org_palm_length * hand_floor_distance):
                            # 手首床調整

                            # 変換先モデルのIK計算前指までの情報
                            _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)
                            # 変換先モデルの反対側IK計算前指までの情報
                            _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)

                            # 手首のY位置
                            rep_wrist_y = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1].y()
                            rep_reverse_wrist_y = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1].y()

                            # 手首を元に合わせるY補正
                            rep_center_diff = (min(org_wrist_y, org_reverse_wrist_y) * arm_diff_length) - min(rep_wrist_y, rep_reverse_wrist_y)

                            # 手首がぺたっと床についている場合、手首の厚み補正
                            rep_wrist_thick = wrist_thickness["左"] if (rep_wrist_y / org_palm_length < 0.5 or rep_reverse_wrist_y / org_palm_length < 0.5 ) else 0

                            # logger.debug("hand_floor wrist: rwy: %s, rwyr: %s", rep_wrist_y, rep_reverse_wrist_y)
                            # logger.debug("hand_floor wrist: (min(org_wrist_y, org_reverse_wrist_y) - min(rep_wrist_y, rep_reverse_wrist_y)): %s", (min(org_wrist_y, org_reverse_wrist_y) - min(rep_wrist_y, rep_reverse_wrist_y)))

                            # logger.debug("%s: is_floor_hand_up: %s, is_floor_hand_down: %s, rep_center_diff: %s", bf.frame, is_floor_hand_up, is_floor_hand_down, rep_center_diff)

                            if (is_floor_hand_up and rep_center_diff > 0) or (is_floor_hand_down and rep_center_diff < 0):
                                # 床位置合わせで、手首のY位置が大体手の大きさ以下の場合、手首と床の位置合わせ
                                motion.frames["センター"][bf_idx].position.setY(motion.frames["センター"][bf_idx].position.y() + rep_center_diff + rep_wrist_thick)
                                motion.frames["センター"][bf_idx].key = True

                                logger.debug("hand_floor wrist: center: %s", motion.frames["センター"][bf_idx].position)

                                print("○手首床近接あり: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, hand_floor_distance, org_direction, org_wrist_y / org_palm_length, reverse_org_direction, org_reverse_wrist_y / org_palm_length, rep_center_diff))
                            else:
                                if (not is_floor_hand_up and rep_center_diff > 0):
                                    print("－手首床近接UP×: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, hand_floor_distance, org_direction, org_wrist_y / org_palm_length, reverse_org_direction, org_reverse_wrist_y / org_palm_length, rep_center_diff))

                                if (not is_floor_hand_down and rep_center_diff < 0):
                                    print("－手首床近接DOWN×: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, hand_floor_distance, org_direction, org_wrist_y / org_palm_length, reverse_org_direction, org_reverse_wrist_y / org_palm_length, rep_center_diff))

                        else:
                            if (org_wrist_y <= org_palm_length * hand_floor_distance * 2 or org_reverse_wrist_y <= org_palm_length * hand_floor_distance * 2):
                                print("－手首床近接なし: f: %s, 境界: %s, %s: %s, %s: %s" % (bf.frame, hand_floor_distance, org_direction, org_wrist_y / org_palm_length, reverse_org_direction, org_reverse_wrist_y / org_palm_length))

                        if (org_leg_y <= org_palm_length * leg_floor_distance or org_reverse_leg_y <= org_palm_length * leg_floor_distance):
                            # 足床調整

                            # 変換先モデルのIK計算前足までの情報
                            _, _, _, _, rep_leg_global_3ds = utils.create_matrix_global(replace_model, all_rep_leg_links[org_direction], motion.frames, bf, None)
                            # 変換先モデルの反対側IK計算前足までの情報
                            _, _, _, _, rep_reverse_leg_global_3ds = utils.create_matrix_global(replace_model, all_rep_leg_links[reverse_org_direction], motion.frames, bf, None)

                            # 足のY位置
                            rep_leg_y = rep_leg_global_3ds[len(rep_leg_global_3ds) - all_rep_leg_indexes[org_direction]["足"] - 1].y()
                            rep_reverse_leg_y = rep_reverse_leg_global_3ds[len(rep_reverse_leg_global_3ds) - all_rep_leg_indexes[reverse_org_direction]["足"] - 1].y()

                            if org_upper_y > org_palm_length * 3:
                                # 起き上がっている場合は下に沈める
                                back_thickness_diff = -back_thickness
                            else:
                                # 寝ている場合は上に起こす
                                back_thickness_diff = back_thickness

                            # 足を元に合わせるY補正
                            rep_center_diff = (min(org_leg_y, org_reverse_leg_y) * arm_diff_length) - min(rep_leg_y, rep_reverse_leg_y) + back_thickness

                            logger.debug("hand_floor leg: oly: %s, olyr: %s", org_leg_y, org_reverse_leg_y)
                            logger.debug("hand_floor leg: rly: %s, rlyr: %s", rep_leg_y, rep_reverse_leg_y)
                            logger.debug("hand_floor leg: rep_center_diff: %s", rep_center_diff)
                            logger.debug("hand_floor leg: center pre: %s", motion.frames["センター"][bf_idx].position)

                            if (is_floor_hand_up and rep_center_diff > 0) or (is_floor_hand_down and rep_center_diff < 0):
                                # 床位置合わせで、足のY位置が大体手の大きさ以下の場合、足と床の位置合わせ
                                motion.frames["センター"][bf_idx].position.setY(motion.frames["センター"][bf_idx].position.y() + rep_center_diff)
                                motion.frames["センター"][bf_idx].key = True

                                logger.debug("hand_floor leg: center: %s", motion.frames["センター"][bf_idx].position)

                                print("○足床近接あり: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, leg_floor_distance, org_direction, org_leg_y / org_palm_length, reverse_org_direction, org_reverse_leg_y / org_palm_length, rep_center_diff))
                            else:
                                if (not is_floor_hand_up and rep_center_diff > 0):
                                    print("－足床近接UP×: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, leg_floor_distance, org_direction, org_leg_y / org_palm_length, reverse_org_direction, org_reverse_leg_y / org_palm_length, rep_center_diff))

                                if (not is_floor_hand_down and rep_center_diff < 0):
                                    print("－足床近接DOWN×: f: %s, 境界: %s, %s: %s, %s: %s, 調整: %s" % (bf.frame, leg_floor_distance, org_direction, org_leg_y / org_palm_length, reverse_org_direction, org_reverse_leg_y / org_palm_length, rep_center_diff))

                        else:
                            if (org_leg_y <= org_palm_length * leg_floor_distance * 2 or org_reverse_leg_y <= org_palm_length * leg_floor_distance * 2):
                                print("－足床近接なし: f: %s, 境界: %s, %s: %s, %s: %s" % (bf.frame, hand_floor_distance, org_direction, org_wrist_y / org_palm_length, reverse_org_direction, org_reverse_wrist_y / org_palm_length))

                        logger.debug("%s: org_wrist_y: %s(%s), org_reverse_wrist_y: %s(%s)", bf.frame, org_wrist_y, org_palm_length * hand_floor_distance, org_reverse_wrist_y, org_palm_length * hand_floor_distance)
                        logger.debug("%s: org_upper_y: %s(%s)(%s)", bf.frame, org_upper_y, org_leg_y * 1.2, org_reverse_leg_y * 1.2)
                        logger.debug("%s: org_leg_y: %s(%s), org_reverse_leg_y: %s(%s)", bf.frame, org_leg_y, org_palm_length * 2, org_reverse_leg_y, org_palm_length * 2)

                        # 手と足を調整して、寝転がっているのではない場合、上半身を調整する
                        # if (org_wrist_y <= org_palm_length * hand_floor_distance or org_reverse_wrist_y <= org_palm_length * hand_floor_distance) and (org_upper_y > org_leg_y * 1.2 or org_upper_y > org_reverse_leg_y * 1.2 or org_leg_y > org_palm_length * 2 or org_reverse_leg_y > org_palm_length * 2 ):
                        if (org_wrist_y <= org_palm_length * hand_floor_distance or org_reverse_wrist_y <= org_palm_length * hand_floor_distance):
                            logger.debug("%s: 上半身調整対象", bf.frame)

                            # 変換先モデルのIK計算前指までの情報
                            _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)
                            # 変換先モデルの反対側IK計算前指までの情報
                            _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)

                            # 手首のY位置
                            rep_wrist_y = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1].y()
                            # 手首のY位置（反対方向）
                            rep_reverse_wrist_y = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1].y()

                            logger.debug("hand_floor wrist-re: (min(org_wrist_y, org_reverse_wrist_y) - min(rep_wrist_y, rep_reverse_wrist_y)): %s", (min(org_wrist_y, org_reverse_wrist_y) - min(rep_wrist_y, rep_reverse_wrist_y)))
                            logger.debug("hand_floor wrist-re: org_wrist_y <= org_palm_length * 1.5: %s", org_wrist_y <= org_palm_length * 1.5)
                            logger.debug("hand_floor wrist-re: abs(org_wrist_y - rep_wrist_y): %s", abs(org_wrist_y - rep_wrist_y))
                            logger.debug("hand_floor wrist-re: org_reverse_wrist_y <= org_palm_length * 1.5: %s", org_reverse_wrist_y <= org_palm_length * 1.5)
                            logger.debug("hand_floor wrist-re: abs(org_reverse_wrist_y - rep_reverse_wrist_y) > 0.3): %s", abs(org_reverse_wrist_y - rep_reverse_wrist_y) > 0.3)

                            if (org_wrist_y <= org_palm_length * hand_floor_distance and (abs(org_wrist_y * arm_palm_diff_length - rep_wrist_y) > 0.6 or rep_wrist_y < 0)) or (org_reverse_wrist_y <= org_palm_length * hand_floor_distance and (abs(org_reverse_wrist_y * arm_palm_diff_length - rep_reverse_wrist_y) > 0.6 or rep_reverse_wrist_y < 0 )):
                                # 差が大きい場合、調整

                                print("○手首床近接あり上半身調整: f: %s, 手首のY位置: %s:%s, %s:%s" % (bf.frame, org_direction, org_wrist_y, reverse_org_direction, org_reverse_wrist_y))

                                rep_wrist_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1]
                                rep_reverse_wrist_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1]
                                logger.debug("hand_floor rep_wrist_pos: %s", rep_wrist_pos)
                                logger.debug("hand_floor rep_reverse_wrist_pos: %s", rep_reverse_wrist_pos)

                                is_wrist_adjust = is_reverse_wrist_adjust = False

                                if org_wrist_y <= org_palm_length * hand_floor_distance  and org_reverse_wrist_y <= org_palm_length * hand_floor_distance:
                                    # 両手首とも床に近い場合

                                    for _ in range(5):
                                        # 変換先モデルの反対側IK計算前指までの情報
                                        _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)
                                        # 逆方向の手首位置
                                        rep_reverse_wrist_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1]

                                        # 逆方向
                                        org_target_y = (org_reverse_wrist_y + 0.1) * arm_diff_length
                                        org_thickness_y = abs(wrist_thickness[reverse_org_direction])
                                        rep_reverse_wrist_pos.setY( org_target_y + org_thickness_y )
                                        logger.debug("hand_floor org_target_y: %s, org_thickness_y: %s", org_target_y, org_thickness_y)
                                        logger.debug("hand_floor rep_reverse_wrist_pos: %s", rep_reverse_wrist_pos)

                                        # 手首位置から角度を求める
                                        calc_arm_IK2FK(rep_reverse_wrist_pos, replace_model, upper_links[reverse_org_direction], all_rep_finger_links[reverse_org_direction], reverse_org_direction, motion.frames, bf, None)

                                        # 変換先モデルのIK計算前指までの情報
                                        _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)
                                        # 正方向の手首位置
                                        rep_wrist_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1]

                                        # 正方向
                                        org_target_y = (org_wrist_y + 0.1) * arm_diff_length
                                        org_thickness_y = abs(wrist_thickness[org_direction])
                                        rep_wrist_pos.setY( org_target_y + org_thickness_y )
                                        logger.debug("hand_floor org_target_y: %s, org_thickness_y: %s", org_target_y, org_thickness_y)
                                        logger.debug("hand_floor rep_wrist_pos: %s", rep_wrist_pos)

                                        # 手首位置から角度を求める
                                        calc_arm_IK2FK(rep_wrist_pos, replace_model, upper_links[org_direction], all_rep_finger_links[org_direction], org_direction, motion.frames, bf, None)

                                    is_wrist_adjust = is_reverse_wrist_adjust = True
                                elif org_wrist_y <= org_palm_length * hand_floor_distance:
                                    # 正方向のYがより床に近い場合
                                    org_target_y = org_wrist_y * arm_diff_length
                                    org_thickness_y = abs(wrist_thickness[org_direction])
                                    rep_wrist_pos.setY( org_target_y + org_thickness_y )
                                    logger.debug("hand_floor org_target_y: %s, org_thickness_y: %s", org_target_y, org_thickness_y)
                                    logger.debug("hand_floor rep_wrist_pos: %s", rep_wrist_pos)

                                    # 手首位置から角度を求める
                                    calc_arm_IK2FK(rep_wrist_pos, replace_model, upper_links[org_direction], all_rep_finger_links[org_direction], org_direction, motion.frames, bf, None)

                                    is_wrist_adjust = True
                                elif org_reverse_wrist_y <= org_palm_length * hand_floor_distance:
                                    # 逆方向のYがより床に近い場合
                                    # Yを元モデルと同じ距離にする
                                    org_target_y = org_reverse_wrist_y * arm_diff_length
                                    org_thickness_y = abs(wrist_thickness[reverse_org_direction])
                                    rep_reverse_wrist_pos.setY( org_target_y + org_thickness_y )
                                    logger.debug("hand_floor org_target_y: %s, org_thickness_y: %s", org_target_y, org_thickness_y)
                                    logger.debug("hand_floor rep_reverse_wrist_pos: %s", rep_reverse_wrist_pos)

                                    # 手首位置から角度を求める
                                    calc_arm_IK2FK(rep_reverse_wrist_pos, replace_model, upper_links[reverse_org_direction], all_rep_finger_links[reverse_org_direction], reverse_org_direction, motion.frames, bf, None)

                                    is_reverse_wrist_adjust = True

                                if finger_links and wrist_thickness[org_direction] != 0 and is_wrist_adjust:
                                    # 人指３のY位置                                    
                                    org_finger_y = org_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[org_direction]["人指３"] - 1].y()

                                    # 変換先モデルのIK計算前指までの情報
                                    _, _, _, _, rep_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[org_direction], motion.frames, bf, None)

                                    rep_wrist_y = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["手首"] - 1].y()
                                    rep_finger_pos = rep_finger_global_3ds[len(rep_finger_global_3ds) - all_rep_finger_indexes[org_direction]["人指３"] - 1]
                                    logger.debug("org_wrist_y: %s, org_finger_y: %s", org_wrist_y, org_finger_y)
                                    logger.debug("rep_wrist_y: %s, rep_finger_pos before: %s", rep_wrist_y, rep_finger_pos)
                                    rep_finger_pos.setY( org_finger_y * arm_diff_length )
                                    logger.debug("rep_wrist_y: %s, rep_finger_pos after: %s", rep_wrist_y, rep_finger_pos)
                                    
                                    # 指３位置から角度を求める
                                    calc_arm_IK2FK(rep_finger_pos, replace_model, finger_links[org_direction], all_rep_finger_links[org_direction], org_direction, motion.frames, bf, None)

                                if finger_links and wrist_thickness[reverse_org_direction] != 0 and is_reverse_wrist_adjust:
                                    # 人指３のY位置
                                    org_reverse_finger_y = org_reverse_finger_global_3ds[len(org_finger_global_3ds) - all_org_finger_indexes[reverse_org_direction]["人指３"] - 1].y()

                                    # 変換先モデルのIK計算前指までの情報
                                    _, _, _, _, rep_reverse_finger_global_3ds = utils.create_matrix_global(replace_model, all_rep_finger_links[reverse_org_direction], motion.frames, bf, None)

                                    # 手首のY位置（反対方向）
                                    rep_reverse_wrist_y = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["手首"] - 1].y()

                                    rep_reverse_finger_pos = rep_reverse_finger_global_3ds[len(rep_reverse_finger_global_3ds) - all_rep_finger_indexes[reverse_org_direction]["人指３"] - 1]
                                    rep_reverse_finger_pos.setY( org_reverse_finger_y * arm_diff_length )

                                    # 指３位置から角度を求める
                                    calc_arm_IK2FK(rep_reverse_finger_pos, replace_model, finger_links[reverse_org_direction], all_rep_finger_links[reverse_org_direction], reverse_org_direction, motion.frames, bf, None)

                                # 指位置調整-----------------

                                if is_wrist_adjust == True or is_reverse_wrist_adjust == True:
                                    logger.debug("motion: %s: %s: 上半身: %s", bf_idx, motion.frames["上半身"][bf_idx].frame, motion.frames["上半身"][bf_idx].rotation.toEulerAngles())
                                    logger.debug("org_motion: %s: %s: 上半身: %s", bf_idx, org_fill_motion_frames["上半身"][bf_idx].frame, org_fill_motion_frames["上半身"][bf_idx].rotation.toEulerAngles())

                                    uad = abs(QQuaternion.dotProduct(motion.frames["上半身"][bf_idx].rotation, org_fill_motion_frames["上半身"][bf_idx].rotation))
                                    if uad < 0.95:
                                        print("%sフレーム目上半身位置合わせ失敗: 上半身:%s" % (bf.frame, uad))
                                        # 失敗時のみエラーログ出力
                                        if not is_error_outputed:
                                            is_error_outputed = True
                                            if not error_file_logger:
                                                error_file_logger = utils.create_error_file_logger(motion, trace_model, replace_model, output_vmd_path)

                                            error_file_logger.info("作成元モデルの手の大きさ: %s", org_palm_length)
                                            error_file_logger.info("変換先モデルの手の大きさ: %s", rep_palm_length)
                                            error_file_logger.info("手首の厚み: l: %s, r: %s", wrist_thickness["左"], wrist_thickness["右"])
                                            # error_file_logger.debug("作成元の上半身の厚み: %s", org_upper_thickness_diff)
                                            # error_file_logger.debug("変換先の上半身の厚み: %s", rep_upper_thickness_diff)
                                            # error_file_logger.debug("肩幅の差: %s" , showlder_diff_length)

                                        error_file_logger.warning("%sフレーム目上半身位置合わせ失敗: 上半身:%s" % (bf.frame, uad))
                                        
                                        # 失敗時は元に戻す
                                        motion.frames["上半身"][bf_idx] = copy.deepcopy(org_fill_motion_frames["上半身"][bf_idx])
                                    else:
                                        logger.debug("手首床位置合わせ成功: f: %s, 上半身:%s", bf.frame, uad)
                                        motion.frames["上半身"][bf_idx].key = True
                                        if is_wrist_adjust:
                                            motion.frames["{0}手首".format(org_direction)][bf_idx].key = True
                                        if is_reverse_wrist_adjust:
                                            motion.frames["{0}手首".format(reverse_org_direction)][bf_idx].key = True
                                        # if "上半身2" in motion.frames:
                                        #     motion.frames["上半身2"][bf_idx].key = True

                    # 前回登録キーとして保持
                    prev_bf = copy.deepcopy(bf)
                        
                    # とりえあずチェックは済んでるのでFLG=ON
                    is_ik_adjust = True

                if is_ik_adjust:
                    # 既にIK調整終了していたら片手分のループを抜ける
                    break
        
            if is_ik_adjust:
                # 既にIK調整終了していたら片手分のループを抜ける
                break
    
    return is_error_outputed

def is_prev_next_enable_key(bone_name, frames, bf_idx, diff=1):
    # 前回が登録対象で前回フレームとdiffFしか離れていない場合、今回をOFF
    # 次回が登録対象で次回フレームとdiffFしか離れていない場合、今回をOFF
    return frames[bone_name][bf_idx].key == False and \
        ((frames[bone_name][bf_idx - 1] and frames[bone_name][bf_idx - 1].key == True and frames[bone_name][bf_idx].frame - frames[bone_name][bf_idx - 1].frame < diff + 1) or\
        ( len(frames[bone_name]) > bf_idx + 1 and frames[bone_name][bf_idx + 1].key == True and frames[bone_name][bf_idx + 1].frame - frames[bone_name][bf_idx].frame < diff + 1 ))

# 手首から指３までで最も離れている関節の距離
def calc_farer_finger_length(finger_global_3ds, all_finger_indexes, direction):
    # 手首の位置
    wrist_pos = finger_global_3ds[len(finger_global_3ds) - all_finger_indexes[direction]["手首"] - 1]
    # 最も離れている指の位置（初期値は手首）
    farer_finger_pos = wrist_pos

    for n in range(len(finger_global_3ds) - all_finger_indexes[direction]["手首"] - 1, len(finger_global_3ds)):
        # 手首から指までの位置情報
        # logger.debug("n: %s, pos: %s", n, finger_global_3ds[n])
        
        if (wrist_pos - finger_global_3ds[n]).length() > (wrist_pos - farer_finger_pos).length():
            # 手首から指３までの距離が、これまでの最長距離より長い場合、保持
            farer_finger_pos = finger_global_3ds[n]
    
    # 最終的に最も遠い関節との距離を返す
    return (wrist_pos - farer_finger_pos).length()

# 指定された方向に向いた場合の位置情報を返す
def create_direction_pos_all(direction_qq, target_pos_3ds):
    direction_pos_3ds = []

    for target_pos in target_pos_3ds:
        direction_pos_3ds.append(create_direction_pos(direction_qq, target_pos))
    
    return direction_pos_3ds

# 指定された方向に向いた場合の位置情報を返す
def create_direction_pos(direction_qq, target_pos):
    mat = QMatrix4x4()
    mat.rotate(direction_qq)
    return mat.mapVector(target_pos)

# IK計算
# https://mukai-lab.org/content/CcdParticleInverseKinematics.pdf
def calc_arm_IK2FK(target_pos, model, joint_links, all_joint_links, direction, frames, bf, prev_bf, maxc=20, reverse_all_joint_links=None):
    local_target_pos = QVector3D()
    local_effector_pos = QVector3D()

    # logger.debug("model: %s", model.name)
    
    for idx in range(maxc):   
        for eidx, effector in enumerate(joint_links):
            # if idx == 3 and eidx == 1:
            #     return

            # logger.debug("idx: %s, eidx: %s, effector: %s ----------------------------------", idx, eidx, effector.name)

            if eidx == len(joint_links) - 1:
                # 一番親は計算外
                break

            # 末端からのINDEX保持
            for afli, afl in enumerate(all_joint_links):
                # logger.debug("afli: %s, afl: %s, joint: %s", afli, afl.name, joint_links[0].name)
                if afl.name == joint_links[0].name:
                    # エフェクターのインデックス
                    effector_idx = afli
                    # logger.debug("afli: %s, eidx: %s, joint_links[eidx].name: %s", afli, eidx, joint_links[eidx].name)
                if afl.name == joint_links[eidx+1].name:
                    # ジョイントのインデックス
                    joint_idx = afli

            # logger.debug("effector_idx: %s, joint_idx: %s, target_pos: %s", effector_idx, joint_idx, target_pos)

            # 腕関節のグローバル位置と局所座標系
            matrixs_global_reversed, global_3d_reversed = calc_arm_matrixs(model, all_joint_links, direction, frames, bf)
            # 反対側も指定されていたら取得する
            if reverse_all_joint_links:
                _, reverse_global_3d_reversed = calc_arm_matrixs(model, reverse_all_joint_links, "右" if direction == "左" else "左", frames, bf)
            
            # for k, v in zip(all_joint_links, global_3d_reversed):
            #     logger.debug("**GROBAL %s pos: %s", k.name, v)
            
            # ジョイント(親)
            joint_name = all_joint_links[joint_idx].name
            joint = None
            if joint_name in frames:
                now_al_bf = [(e, x) for e, x in enumerate(frames[joint_name]) if x.frame == bf.frame]
                if len(now_al_bf) > 0:
                    joint = now_al_bf[0][1]
                # for jidx, jbf in enumerate(frames[joint_name]):
                #     if jbf.frame == bf.frame:
                #         # logger.debug("補間不要 bf.frame: %s %s", bf.frame, joint_name)
                #         # 既存の場合は、それを選ぶ
                #         joint = frames[joint_name][jidx]
                #         # # 登録対象
                #         # joint.key = True
                #         break
                        
            if joint == None:
                # ない場合は、補間曲線込みで生成
                joint = utils.calc_bone_by_complement(frames, joint_name, bf.frame)
                if joint_name in frames:
                    for jidx, jbf in enumerate(frames[joint_name]):
                        # logger.debug("補間チェック: jbf: %s, joint: %s", jbf.frame, joint.frame)
                        if jbf.frame > joint.frame:
                            # logger.debug("要補間 bf.frame: %s %s, jidx: %s, jbf: %s, jf: %s", bf.frame, joint_name, jidx, jbf.frame, joint.frame)
                            # # 現時点では登録対象としない
                            # joint.key = False
                            # フレームを越えたトコで、その直前に挿入
                            frames[joint_name].insert( jidx, joint )
                            break

                    for jidx, jbf in enumerate(frames[joint_name]):
                        # logger.debug("補間後: jbf: %s, joint: %s", jbf.frame, joint.frame)
                        if jbf.frame == joint.frame:
                            break
                else:
                    frames[joint_name] = []
                    frames[joint_name].append(joint)
                
            # エフェクタのグローバル位置
            # 現在地点が固定で指定されている場合、そこをエフェクタ位置にする
            global_effector_pos = global_3d_reversed[effector_idx]
            # 反対も指定されている場合、エフェクタの中間を取得する
            if reverse_all_joint_links:
                global_effector_pos = (global_3d_reversed[effector_idx] + reverse_global_3d_reversed[effector_idx]) / 2
                # # Yは低い方を採用
                # global_effector_pos.setY(min(global_3d_reversed[effector_idx].y(), reverse_global_3d_reversed[effector_idx].y()))

            # 注目ノードのグローバル位置
            global_joint_pos = global_3d_reversed[joint_idx]
            
            # logger.debug("%s %s: global_effector_pos: %s", effector_idx, all_joint_links[effector_idx].name, global_effector_pos)
            # logger.debug("%s %s: global_joint_pos: %s", effector_idx, all_joint_links[joint_idx].name, global_joint_pos)
            
            # ワールド座標系から注目ノードの局所座標系への変換
            inv_coord = matrixs_global_reversed[joint_idx].inverted()[0]
            
            # logger.debug("%s %s: inv_coord:  %s", joint_idx, all_joint_links[joint_idx].name, inv_coord)

            # 注目ノードを起点とした、エフェクタのローカル位置
            local_effector_pos = inv_coord * global_effector_pos
            local_target_pos = inv_coord * target_pos
            
            # logger.debug("%s %s: local_effector_pos:  %s", effector_idx, all_joint_links[effector_idx].name, local_effector_pos)
            # logger.debug("%s %s: local_target_pos: %s", effector_idx, all_joint_links[effector_idx].name, local_target_pos)

            #  (1) 基準関節→エフェクタ位置への方向ベクトル
            basis2_effector = local_effector_pos.normalized()
            #  (2) 基準関節→目標位置への方向ベクトル
            basis2_target = local_target_pos.normalized()

            # logger.debug("%s %s: basis2_effector: %s", effector_idx, all_joint_links[effector_idx].name, basis2_effector)
            # logger.debug("%s %s: basis2_target: %s", effector_idx, all_joint_links[effector_idx].name, basis2_target)
            
            # ベクトル (1) を (2) に一致させるための最短回転量（Axis-Angle）
            # 回転角
            rotation_dot_product = QVector3D.dotProduct(basis2_effector, basis2_target)
            rotation_dot_product = 1 if rotation_dot_product > 1 else rotation_dot_product
            rotation_dot_product = 0 if rotation_dot_product < 0 else rotation_dot_product
            rotation_angle = acos(rotation_dot_product)
            
            # logger.debug("%s %s: rotation_angle: %s", joint_idx, all_joint_links[joint_idx].name, rotation_angle)

            if abs(rotation_angle) > 0.00001:
                # 一定角度以上の場合
                # 回転軸
                rotation_axis = QVector3D.crossProduct(basis2_effector, basis2_target)
                # logger.debug("[B-1]joint.name: %s, axis: %s", joint.format_name, rotation_axis)

                rotation_axis.normalize()
                rotation_degree = degrees(rotation_angle)
                # logger.debug("[B-2]joint.name: %s, axis: %s", joint.format_name, rotation_axis)

                # 関節回転量の補正
                correct_qq = QQuaternion.fromAxisAndAngle(rotation_axis, rotation_degree)
                # logger.debug("f: %s, joint: %s, correct_qq: %s", bf.frame, joint.format_name, correct_qq.toEulerAngles())

                # エフェクタのローカル軸
                # logger.debug("joint: %s, joint before: %s", all_joint_links[joint_idx].name, joint.rotation.toEulerAngles())
                logger.debug("joint: %s, correct_qq: %s", all_joint_links[joint_idx].name, correct_qq.toEulerAngles())

                joint.rotation = correct_qq * joint.rotation

                logger.debug("joint: %s, joint after: %s", joint.format_name, joint.rotation.toEulerAngles())

                # logger.debug("[A]joint.name: %s, rotation: %s, correct_qq: %s", joint.format_name, joint.rotation.toEulerAngles(), correct_qq.toEulerAngles())
            else:
                # logger.debug("[X]回転なし: %s %s", joint.format_name, rotation_angle)
                pass
            
        # logger.debug("IK: sq: %s, local_effector_pos: %s, local_target_pos: %s", (local_effector_pos - local_target_pos).lengthSquared(), local_effector_pos, local_target_pos)
        if (local_effector_pos - local_target_pos).lengthSquared() < 0.0001:
            # logger.debug("IK break: sq: %s, local_effector_pos: %s, local_target_pos: %s", (local_effector_pos - local_target_pos).lengthSquared(), local_effector_pos, local_target_pos)
            return True
    
    return False

# 行列とグローバル位置を反転させて返す（末端が0）
def calc_arm_matrixs(model, all_wrist_links, direction, frames, bf):
    # 行列生成(センター起点)
    _, _, _, org_matrixs, org_global_3ds = utils.create_matrix_global(model, all_wrist_links, frames, bf)

    # 該当ボーンの局所座標系変換
    matrixs = [QMatrix4x4() for i in range(len(all_wrist_links))]
    matrixs_global_reversed = [QMatrix4x4() for i in range(len(all_wrist_links))]  

    # グローバル座標
    for n, (v, l) in enumerate(zip(org_matrixs, reversed(all_wrist_links))):
        for m in range(n):
            if m == 0:
                # 最初は行列
                matrixs[n] = copy.deepcopy(org_matrixs[0])
            else:
                # 2番目以降は行列をかける
                matrixs[n] *= copy.deepcopy(org_matrixs[m])
        
        # # ローカル軸が設定されていない場合、設定
        # local_x_matrix = QMatrix4x4()
        # if l.local_x_vector == QVector3D() and "指" in l.name:
        #     local_axis = l.position - all_wrist_links[len(all_wrist_links) - n].position
        #     direction_x = 1 if direction == "左" else -1
        #     local_axis_qq = QQuaternion.rotationTo(QVector3D(direction_x, 0, local_axis.z()), local_axis)
        #     # logger.debug("l.name: %s -> %s, %s", all_wrist_links[len(all_wrist_links) - n - 1].name, all_wrist_links[len(all_wrist_links) - n].name, local_axis_qq.toEulerAngles())
        #     local_x_matrix.rotate(local_axis_qq)
        
        # matrixs[n] *= local_x_matrix

    # 末端からとして収め直す
    for n, m in enumerate(reversed(matrixs)):
        # グローバル座標行列
        matrixs_global_reversed[n] = m

    # グローバル座標(ルート反転)
    global_3ds_reversed = [QVector3D() for i in range(len(org_global_3ds))]
        
    for n, g in enumerate(reversed(org_global_3ds)):
        global_3ds_reversed[n] = g
    
    return matrixs_global_reversed, global_3ds_reversed


# 指ジョイントリスト生成
def create_finger_links(model, links, direction):

    # 関節リストを末端から生成する
    finger_links = []

    finger_links.append(get_bone_in_links_4_joint(model, links, direction, "人指３", "人指３"))

    finger_links.append(get_bone_in_links_4_joint(model, links, direction, "手首", "人指３"))
    
    return finger_links
    
def create_upper_links(model, links, direction):
    # 関節リストを末端から生成する
    upper_links = []

    upper_links.append(get_bone_in_links_4_joint(model, links, direction, "手首", "手首"))

    # if "上半身2" in model.bones:
    #     upper_links.append(model.bones["上半身2"])
    
    upper_links.append(model.bones["上半身"])

    return upper_links

# 腕ジョイントリスト生成
def create_arm_links(model, links, direction):
    
    # 関節リストを末端から生成する
    arm_links = []
    
    # if "{0}人指１".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}人指１".format(direction)])

    arm_links.append(get_bone_in_links_4_joint(model, links, direction, "手首", "手首"))
    
    # if "{0}手捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}手捩".format(direction)])

    arm_links.append(get_bone_in_links_4_joint(model, links, direction, "ひじ", "手首"))
    
    # if "{0}腕捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}腕捩".format(direction)])

    arm_links.append(get_bone_in_links_4_joint(model, links, direction, "腕", "手首"))
    # arm_links.append(get_bone_in_links_4_joint(model, links, direction, "肩", "手首"))
    
    # logger.debug([x.name for x in arm_links])

    return arm_links

# 腕ジョイントリスト生成
def create_arm_finger_links(model, links, indexes, direction, joint_name, is_wrist=False):
    
    # 関節リストを末端から生成する
    arm_finger_links = []
    
    # if "{0}人指１".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}人指１".format(direction)])

    arm_finger_links.append(links[indexes[joint_name]])

    if is_wrist and joint_name != "手首":
        arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "手首", joint_name))
    
    # if "{0}手捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}手捩".format(direction)])

    arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "ひじ", joint_name))
    
    # if "{0}腕捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}腕捩".format(direction)])

    arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "腕", joint_name))
    # arm_links.append(get_bone_in_links_4_joint(model, links, direction, "肩", "手首"))
    
    # logger.debug([x.name for x in arm_links])

    return arm_finger_links

# 腕ジョイントリスト生成
def create_arm_wrist_finger_links(model, links, indexes, direction, joint_name):
    
    # 関節リストを末端から生成する
    arm_finger_links = []
    
    # if "{0}人指１".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}人指１".format(direction)])

    arm_finger_links.append(links[indexes[joint_name]])

    if joint_name != "手首":
        arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "手首", joint_name))
    
    # if "{0}手捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}手捩".format(direction)])

    arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "ひじ", joint_name))
    
    # if "{0}腕捩".format(direction) in model.bones:
    #     arm_links.append(model.bones["{0}腕捩".format(direction)])

    arm_finger_links.append(get_bone_in_links_4_joint(model, {direction: links}, direction, "腕", joint_name))
    # arm_links.append(get_bone_in_links_4_joint(model, links, direction, "肩", "手首"))
    
    # logger.debug([x.name for x in arm_links])

    return arm_finger_links

# ジョイント用：リンクからボーン情報を取得して返す
def get_bone_in_links_4_joint(model, links, direction, bone_type_name, start_bone_type_name):
    target_bone_name = "{0}{1}".format(direction, bone_type_name)

    for l in links[direction]:
        # logger.debug("l: %s, target_bone_name:%s", l, target_bone_name)
        if l.name == target_bone_name:
            # ちゃんとリンクの中にボーンがあれば、それを返す
            return model.bones[target_bone_name]

    # リストの中に対象ボーンがない場合、エラー
    raise SizingException("ジョイントリストに{0}が登録できません。\n{1}からセンターに向けての親ボーンの繋がりの中に{0}が含まれていません。\nボーンリンク: {2}".format(target_bone_name, "{0}{1}".format(direction, start_bone_type_name), [ x.name for x in links[direction]]))
