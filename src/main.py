# -*- coding: utf-8 -*-
#
import argparse
import os.path
import logging
import traceback
import re
import copy
from datetime import datetime
from pathlib import Path
from PyQt5.QtGui import QQuaternion, QVector3D, QVector2D, QMatrix4x4, QVector4D

from VmdWriter import VmdWriter, VmdBoneFrame
from VmdReader import VmdReader
from PmxModel import PmxModel, SizingException
from PmxReader import PmxReader
import utils, sub_move, sub_arm_stance, sub_avoidance, sub_arm_ik, sub_morph, sub_camera, sub_camera2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VmdSizing").getChild(__name__)

level = {0:logging.ERROR,
            1:logging.WARNING,
            2:logging.INFO,
            3:logging.DEBUG}

def main(motion, trace_model, replace_model, output_vmd_path, \
    is_avoidance, is_avoidance_finger, is_hand_ik, hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, hand_floor_distance, leg_floor_distance, is_finger_ik, finger_distance, vmd_choice_values, rep_choice_values, rep_rate_values, \
    camera_motion, camera_vmd_path, camera_pmx, output_camera_vmd_path, camera_y_offset):   
    # print("モーション: %s" % motion.path)
    # if camera_motion:
    #     print("カメラモーション: %s" % camera_motion.path)
    # print("作成元: %s" % trace_model.path)
    # print("変換先: %s" % replace_model.path)

    # 変換前のオリジナルモーションを保持
    org_motion_frames = copy.deepcopy(motion.frames)

    # 処理に成功しているか
    is_success = True

    # 移動系ボーン縮尺処理
    is_success = sub_move.exec(motion, trace_model, replace_model, output_vmd_path) and is_success

    # 腕スタンス補正処理
    is_success = sub_arm_stance.exec(motion, trace_model, replace_model, output_vmd_path) and is_success

    # 腕IK処理
    is_success = sub_arm_ik.exec(motion, trace_model, replace_model, output_vmd_path, is_avoidance, is_hand_ik, hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, hand_floor_distance, leg_floor_distance, is_finger_ik, finger_distance, org_motion_frames) and is_success

    # カメラ処理
    # is_success = sub_camera.exec(motion, trace_model, replace_model, output_vmd_path) and is_success
    # カメラの元モデルは、カメラ用PMXデータ
    is_success = sub_camera.exec(motion, camera_pmx, replace_model, output_vmd_path, org_motion_frames, camera_motion, camera_y_offset) and is_success

    # 頭部と腕の接触回避処理
    is_success = sub_avoidance.exec(motion, trace_model, replace_model, output_vmd_path, is_avoidance, is_avoidance_finger, is_hand_ik) and is_success

    # モーフ処理
    is_success = sub_morph.exec(motion, trace_model, replace_model, output_vmd_path, vmd_choice_values, rep_choice_values, rep_rate_values) and is_success

    # ディクショナリ型の疑似二次元配列から、一次元配列に変換
    bone_frames = []
    for k,v in motion.frames.items():
        for bf in v:
            # if bf.frame == 605:
            #     logger.debug("check: %s, %s, %s, %s, %s, %s", k, bf.name, bf.frame, bf.key, bf.position, bf.rotation)

            if bf.key == True:
                # logger.debug("regist: %s, %s, %s, %s, %s", k, bf.name, bf.frame, bf.position, bf.rotation)
                bone_frames.append(bf)
    
    morph_frames = []
    for k,v in motion.morphs.items():
        for mf in v:
            # logger.debug("k: %s, mf: %s, %s", k, mf.frame, mf.ratio)
            morph_frames.append(mf)

    logger.debug("bone_frames: %s", len(bone_frames))
    logger.debug("morph_frames: %s", len(morph_frames))

    writer = VmdWriter()
    
    # ボーンモーション生成
    writer.write_vmd_file(output_vmd_path, replace_model.name, bone_frames, morph_frames, [], [], [], motion.showiks)

    camera_frames = []
    
    if camera_motion:
        # カメラモーション生成
        for cf in camera_motion.cameras:
            camera_frames.append(cf)

        writer.write_vmd_file(output_camera_vmd_path, replace_model.name, [], [], camera_frames, motion.lights, motion.shadows, [])

    print("■■■■■■■■■■■■■■■■■")
    print("■　変換出力完了: %s" % output_vmd_path)

    if camera_motion:
        print("■　カメラ変換出力完了: %s" % output_camera_vmd_path)

    print("■■■■■■■■■■■■■■■■■")

    return is_success



if __name__=="__main__":
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--vmd_path', dest='vmd_path', help='input vmd', type=str)
    parser.add_argument('--trace_pmx_path', dest='trace_pmx_path', help='input trace pmx', type=str)
    parser.add_argument('--replace_pmx_path', dest='replace_pmx_path', help='replace trace pmx', type=str)
    parser.add_argument('--avoidance', dest='avoidance', help='upper hand avoidance', type=int)
    parser.add_argument('--avoidance_finger', dest='avoidance_finger', help='is_avoidance_finger', type=int)
    parser.add_argument('--hand_ik', dest='hand_ik', help='hand ik', type=int)
    parser.add_argument('--hand_distance', dest='hand_distance', help='hand distance', type=float)
    parser.add_argument('--floor_hand', dest='floor_hand', help='floor_hand', type=int)
    parser.add_argument('--floor_hand_up', dest='floor_hand_up', help='floor_hand_up', type=int)
    parser.add_argument('--floor_hand_down', dest='floor_hand_down', help='floor_hand_down', type=int)
    parser.add_argument('--hand_floor_distance', dest='hand_floor_distance', help='hand_floor_distance', type=float)
    parser.add_argument('--leg_floor_distance', dest='leg_floor_distance', help='leg_floor_distance', type=float)
    parser.add_argument('--finger_ik', dest='finger_ik', help='finger_ik', type=int)
    parser.add_argument('--finger_distance', dest='finger_distance', help='finger_distance', type=float)
    parser.add_argument('--vmd_choice_values', dest='vmd_choice_values', help='vmd_choice_values', default="", type=str)
    parser.add_argument('--rep_choice_values', dest='rep_choice_values', help='rep_choice_values', default="", type=str)
    parser.add_argument('--rep_rate_values', dest='rep_rate_values', help='rep_rate_values', default="", type=str)
    parser.add_argument('--camera_vmd_path', dest='camera_vmd_path', help='camera_vmd_path', type=str)
    parser.add_argument('--camera_pmx_path', dest='camera_pmx_path', help='camera_pmx_path', type=str)
    parser.add_argument('--camera_y_offset', dest='camera_y_offset', help='camera_y_offset', type=float)
    parser.add_argument('--verbose', dest='verbose', help='verbose', type=int)
    args = parser.parse_args()

    logger.setLevel(level[args.verbose])

    try:
        # VMD読み込み
        motion = VmdReader().read_vmd_file(args.vmd_path)

        # 作成元モデル
        logger.debug("trace_pmx_path: %s", args.trace_pmx_path)
        trace_model = PmxReader().read_pmx_file(args.trace_pmx_path)

        # 変換先モデル
        logger.debug("replace_pmx_path: %s", args.replace_pmx_path)
        replace_model = PmxReader().read_pmx_file(args.replace_pmx_path)

        # 出力ファイルパス
        bone_filename, _ = os.path.splitext(os.path.basename(args.replace_pmx_path))
        output_vmd_path = os.path.join(str(Path(args.vmd_path).resolve().parents[0]), os.path.basename(args.vmd_path).replace(".vmd", "_{1}_{0:%Y%m%d_%H%M%S}.vmd".format(datetime.now(), bone_filename)))

        # 接触回避処理
        is_avoidance = True if args.avoidance == 1 else False

        # 腕IKによる位置調整
        is_hand_ik = True if args.hand_ik == 1 else False

        is_avoidance_finger = True if args.avoidance_finger == 1 else False

        is_floor_hand = True if args.floor_hand == 1 else False
        is_floor_hand_up = True if args.floor_hand_up == 1 else False
        is_floor_hand_down = True if args.floor_hand_down == 1 else False
        is_finger_ik = True if args.finger_ik == 1 else False

        camera_motion = None
        output_camera_vmd_path = None
        if args.camera_vmd_path:
            camera_motion = VmdReader().read_vmd_file(args.camera_vmd_path)
            # 出力ファイルパス
            bone_filename, _ = os.path.splitext(os.path.basename(args.replace_pmx_path))
            output_camera_vmd_path = os.path.join(str(Path(args.camera_vmd_path).resolve().parents[0]), os.path.basename(args.camera_vmd_path).replace(".vmd", "_{1}_{0:%Y%m%d_%H%M%S}.vmd".format(datetime.now(), bone_filename)))

        camera_pmx = None
        if args.camera_pmx_path:
            camera_pmx = VmdReader().read_vmd_file(args.camera_pmx_path)


        main(motion, trace_model, replace_model, output_vmd_path, \
            is_avoidance, is_avoidance_finger, is_hand_ik, args.hand_distance, is_floor_hand, is_floor_hand_up, is_floor_hand_down, args.hand_floor_distance, args.leg_floor_distance, \
            is_finger_ik, args.finger_distance, args.vmd_choice_values.split(","), args.rep_choice_values.split(","), args.rep_rate_values.split(","), \
            camera_motion, args.camera_vmd_path, camera_pmx, output_camera_vmd_path, args.camera_y_offset)

    except SizingException as e:
        print("■■■■■■■■■■■■■■■■■")
        print("■　**ERROR**　")
        print("■　VMDサイジング処理が処理できないデータで終了しました。")
        print("■■■■■■■■■■■■■■■■■")
        print("")
        print(e.message)

    except Exception as e:
        print("■■■■■■■■■■■■■■■■■")
        print("■　**ERROR**　")
        print("■　VMDサイジング処理が意図せぬエラーで終了しました。")
        print("■■■■■■■■■■■■■■■■■")

        print(traceback.format_exc())

