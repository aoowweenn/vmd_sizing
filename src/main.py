# -*- coding: utf-8 -*-
#
import argparse
import math
import numpy as np
import os
import datetime
from pathlib import Path
from PyQt5.QtGui import QQuaternion, QVector3D, QMatrix4x4, QVector4D
import logging
import csv
import copy

from VmdWriter import VmdWriter, VmdBoneFrame
from VmdReader import VmdReader
from ModelBone import ModelBone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

level = {0:logging.ERROR,
            1:logging.WARNING,
            2:logging.INFO,
            3:logging.DEBUG}

def main(vmd_path, trace_bone_path, replace_bone_path, replace_vertex_path):   
    logger.info("vmd: %s", vmd_path)
    logger.info("トレース元: %s", trace_bone_path)
    logger.info("トレース先(ボーン): %s", replace_bone_path)
    logger.info("トレース先(頂点): %s", replace_vertex_path)

    # ボーンCSVファイル名・拡張子
    bone_filename, _ = os.path.splitext(os.path.basename(replace_bone_path))

    # VMD読み込み
    reader = VmdReader()
    motion = reader.read_vmd_file(vmd_path)

    # トレース元モデル
    trace_model = load_model_bones(trace_bone_path)

    # トレース移植先モデル
    replace_model = load_model_bones(replace_bone_path)

    # 移植先のセンターとグルーブは、トレース元の比率に合わせる
    adjust_center(trace_model, replace_model, "センター")
    adjust_center(trace_model, replace_model, "グルーブ")

    # サイズ比較
    lengths = compare_length(trace_model, replace_model)

    # 頂点ファイルがある場合、展開
    replace_vertex = load_model_vertexs(replace_model, replace_vertex_path)

    # 変換サイズに合わせてモーション変換
    for k, v in motion.frames.items():
        for bf in v:
            if k in lengths:
                if k == "右足ＩＫ" or k == "左足ＩＫ":
                    # 移動量を倍率変換
                    bf.position = bf.position * lengths[k]
                elif k == "センター" or k == "グルーブ":
                    # 移動量を倍率変換
                    bf.position = bf.position * lengths[k]
                else:
                    if k in ["左肩" ,"左腕" ,"左腕捩" ,"左ひじ" ,"左手捩" ,"左手首","右肩" ,"右腕" ,"右腕捩" ,"右ひじ" ,"右手捩" ,"右手首"] and bf.key == True and replace_vertex is not None:
                        # 腕系登録対象かつ頂点CSVが存在している場合
                        
                        # 方向
                        direction = "左" if "左" in k else "右"
                        # 回転調整
                        adjust_by_hand(replace_model, direction, motion.frames, bf, replace_vertex)

    new_filepath = os.path.join(str(Path(vmd_path).resolve().parents[0]), os.path.basename(vmd_path).replace(".vmd", "_{1}_{0:%Y%m%d_%H%M%S}.vmd".format(datetime.datetime.now(), bone_filename)))

    # ディクショナリ型の疑似二次元配列から、一次元配列に変換
    # 補間曲線を埋めたデータから生成
    bone_frames = []
    for k,v in motion.frames.items():
        for bf in v:
            if bf.key == True:
                # logger.debug("regist: %s, %s, %s, %s, %s", k, bf.name, bf.frame, bf.position, bf.rotation)
                bone_frames.append(bf)
    
    morph_frames = []
    for k,v in motion.morphs.items():
        for mf in v:
            # logger.debug("k: %s, mf: %s, %s", k, mf.frame, mf.ratio)
            morph_frames.append(mf)

    writer = VmdWriter()
    writer.write_vmd_file(new_filepath, bone_frames, morph_frames, None)

    logger.info("output: %s", new_filepath)


# 補間曲線を求める
# http://d.hatena.ne.jp/edvakf/20111016/1318716097
def calc_interpolate_bezier(x1v, y1v, x2v, y2v, start, end, now):
    x = (now - start) / (end - start)
    x1 = x1v / 127
    x2 = x2v / 127
    y1 = y1v / 127
    y2 = y2v / 127

    t = 0.5
    s = 0.5

    # logger.debug("x1: %s, x2: %s, y1: %s, y2: %s, x: %s", x1, x2, y1, y2, x)

    for i in range(15):
        ft = (3 * (s * s) * t * x1) + (3 * s * (t * t) * x2) + (t * t * t) - x
        # logger.debug("i: %s, 4 << i: %s, ft: %s(%s), t: %s, s: %s", i, (4 << i), ft, abs(ft) < 0.00001, t, s)

        if abs(ft) < 0.00001:
            break

        if ft > 0:
            t -= 1 / (4 << i)
        else:
            t += 1 / (4 << i)
        
        s = 1 - t

    y = (3 * (s * s) * t * y1) + (3 * s * (t * t) * y2) + (t * t * t)

    # logger.debug("y: %s, t: %s, s: %s", y, t, s)

    return y

# 手の調整
def adjust_by_hand(replace_model, direction, frames, bf, replace_vertex, cnt=0):
    logger.debug("adjust_by_hand: %s, %s ------------------", cnt, bf.frame )

    # 手首の位置
    finger_pos = calc_finger(replace_model, direction, frames, bf)

    if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
        logger.debug("接触無し frame: %s, finger: %s", bf.frame, finger_pos)
        return

    # 腕調整
    adjust_by_arm_bone(replace_model, direction, frames, bf, replace_vertex, "{0}腕".format(direction))
    if cnt % 3 == 0:
        # ひじ調整
        adjust_by_elbow_bone(replace_model, direction, frames, bf, replace_vertex, "{0}ひじ".format(direction))

    if cnt < 10:
        # 3点調整してもまだ頭の中に入っていたら、自分を再呼び出し
        return adjust_by_hand(replace_model, direction, frames, bf, replace_vertex, cnt+1)
    else:
        # 10回呼び出してもダメならその時点のを返す
        logger.info("接触解消失敗 frame: %s, finger: %s", bf.frame, finger_pos)
        return

def adjust_by_arm_bone(replace_model, direction, frames, bf, replace_vertex, bone_name):
    # 調整値
    av = 0.9

    # ボーン -------------
    bone_idx, _ = get_prev_bf(frames, bone_name, bf.frame)
    ea = frames[bone_name][bone_idx].rotation.toEulerAngles()

    # ボーン - Z調整
    logger.debug("eav prev: %s, %s", ea, av)
    ea.setZ( ea.z() * av )
    logger.debug("eav after: %s, %s", ea, av)
    frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    finger_pos = calc_finger(replace_model, direction, frames, bf)
    logger.debug("bone-z bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
        logger.info("接触解消-z frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
        return

    # ボーン - Y調整
    ea.setY( ea.y() * av )
    frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    finger_pos = calc_finger(replace_model, direction, frames, bf)
    logger.debug("bone-y bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
        logger.info("接触解消-y frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
        return

    # # ボーン - X調整
    # logger.debug("eax prev: %s, %s", ea, av)
    # ea.setX( ea.x() * av )
    # logger.debug("eax after: %s, %s", ea, av)
    # frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    # finger_pos = calc_finger(replace_model, direction, frames, bf)
    # logger.debug("bone-x bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    # if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
    #     logger.info("接触解消-x frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
    #     return

def adjust_by_elbow_bone(replace_model, direction, frames, bf, replace_vertex, bone_name):
    # 調整値
    av = 0.9

    # ボーン -------------
    bone_idx, _ = get_prev_bf(frames, bone_name, bf.frame)
    ea = frames[bone_name][bone_idx].rotation.toEulerAngles()

    # ボーン - Y調整
    ea.setY( ea.y() * av )
    frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    finger_pos = calc_finger(replace_model, direction, frames, bf)
    logger.debug("bone-y bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
        logger.info("接触解消-y frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
        return

    # ボーン - Z調整
    logger.debug("eav prev: %s, %s", ea, av)
    ea.setZ( ea.z() * av )
    logger.debug("eav after: %s, %s", ea, av)
    frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    finger_pos = calc_finger(replace_model, direction, frames, bf)
    logger.debug("bone-z bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
        logger.info("接触解消-z frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
        return

    # # ボーン - X調整
    # logger.debug("eax prev: %s, %s", ea, av)
    # ea.setX( ea.x() * av )
    # logger.debug("eax after: %s, %s", ea, av)
    # frames[bone_name][bone_idx].rotation = QQuaternion.fromEulerAngles(ea)
    # finger_pos = calc_finger(replace_model, direction, frames, bf)
    # logger.debug("bone-x bone: %s, finger: %s", frames[bone_name][bone_idx].rotation.toEulerAngles(), finger_pos )
    # if is_inner_head(finger_pos, replace_model, replace_vertex, direction) == False:
    #     logger.info("接触解消-x frame: %s %s, finger: %s", bone_name, bf.frame, finger_pos)
    #     return


# 指定されたフレームより前のキーを返す
def get_prev_bf(frames, bone_name, frameno):
    for bidx, bf in enumerate(frames[bone_name]):
        if bf.frame >= frameno:
            # 指定されたフレーム以降の一つ前で、前のキーを取る
            return bidx, frames[bone_name][bidx - 1]

    # 最後まで取れなければ、最終項目
    return len(frames[bone_name] - 1), frames[bone_name][-1]

# 頭の中に入っているか
def is_inner_head(finger_pos, replace_model, replace_vertex, direction):
    shoulder_y = 0 if "左肩" not in replace_model else replace_model["左肩"].position.y()
    logger.debug("shoulder_y: %s", shoulder_y)

    if shoulder_y > finger_pos.y():
        # 肩より手首が下ならとりあえずFalse
        return False
    
    for v in replace_vertex:
        if direction == "左" and v.x() > finger_pos.x() and v.z() > finger_pos.z():
            logger.debug("左頭接触: v: %s, w: %s", v, finger_pos)
            # 左手で顔より内側ならTrue
            return True
        if direction == "右" and v.x() < finger_pos.x() and v.z() < finger_pos.z():
            # 右手で顔より内側ならTrue
            logger.debug("右頭接触: v: %s, w: %s", v, finger_pos)
            return True

    # どれもヒットしなければFalse
    return False            


# 中指の位置の計算
def calc_finger(model_bone, direction, frames, bf):

    # ローカル位置
    trans_vs = [0 for i in range(7)]
    # 肩のローカル位置
    trans_vs[0] = model_bone["{0}肩".format(direction)].position

    # 腕捩りのローカル位置
    wrist_twist = QVector3D(0, 0, 0)
    if "{0}腕捩".format(direction) in model_bone:
        # 腕捻りはある場合はそれを設定
        trans_vs[1] = model_bone["{0}腕捩".format(direction)].position - model_bone["{0}肩".format(direction)].position
        wrist_twist = model_bone["{0}腕捩".format(direction)].position
    else:
        # 腕捻りがない場合、肩と腕の中間
        shoulder = model_bone["{0}肩".format(direction)].position
        arm = model_bone["{0}腕".format(direction)].position
        wrist_twist = shoulder + (arm - shoulder) / 2
        trans_vs[1] = wrist_twist - model_bone["{0}肩".format(direction)].position

    # 腕のローカル位置
    trans_vs[2] = model_bone["{0}腕".format(direction)].position - wrist_twist
    # ひじのローカル位置
    trans_vs[3] = model_bone["{0}ひじ".format(direction)].position - model_bone["{0}腕".format(direction)].position

    # 手捩のローカル位置
    hand_twist = QVector3D(0, 0, 0)
    if "{0}手捩".format(direction) in model_bone:
        # 手捻りはある場合はそれを設定
        trans_vs[4] = model_bone["{0}手捩".format(direction)].position - model_bone["{0}ひじ".format(direction)].position
        hand_twist = model_bone["{0}手捩".format(direction)].position
    else:
        # 手捻りがない場合、ひじと手首の中間
        elbow = model_bone["{0}ひじ".format(direction)].position
        wrist = model_bone["{0}手首".format(direction)].position
        hand_twist = elbow + (wrist - elbow) / 2

        trans_vs[4] = hand_twist - model_bone["{0}ひじ".format(direction)].position

    # 手首のローカル位置
    trans_vs[5] = model_bone["{0}手首".format(direction)].position - hand_twist
    # 中指のローカル位置
    trans_vs[6] = model_bone["{0}中指３".format(direction)].position - model_bone["{0}手首".format(direction)].position
    
    # 加算用クォータニオン
    add_qs = [0 for i in range(7)]
    # 肩の回転
    add_qs[0] = calc_rotation_by_complement(frames, "{0}肩".format(direction), bf.frame)

    # 腕捩りの回転
    if "{0}腕捩".format(direction) in model_bone:
        # 腕捻りはある場合はそれを設定
        add_qs[1] = calc_rotation_by_complement(frames, "{0}腕捩".format(direction), bf.frame)
    else:
        add_qs[1] = QQuaternion()

    # 腕の回転
    add_qs[2] = calc_rotation_by_complement(frames, "{0}腕".format(direction), bf.frame)
    # ひじの回転
    add_qs[3] = calc_rotation_by_complement(frames, "{0}ひじ".format(direction), bf.frame)

    # 手捩の回転
    if "{0}手捩".format(direction) in model_bone:
        # 手捻りはある場合はそれを設定
        add_qs[4] = calc_rotation_by_complement(frames, "{0}手捩".format(direction), bf.frame)
    else:
        add_qs[4] = QQuaternion()

    # 手首の回転
    add_qs[5] = calc_rotation_by_complement(frames, "{0}手首".format(direction), bf.frame)
    # 中指の回転(初期値)
    add_qs[6] = QQuaternion()

    # 行列
    matrixs = [0 for i in range(7)]

    for n in range(len(matrixs)):
        # 行列を生成
        matrixs[n] = QMatrix4x4()
        # 移動
        matrixs[n].translate(trans_vs[n])
        # 回転
        matrixs[n].rotate(add_qs[n])

        # logger.debug("matrixs n: %s, %s", n, matrixs[n])

    # 手首の位置
    finger_pos = matrixs[0] * matrixs[1] * matrixs[2] * matrixs[3] * matrixs[4] * matrixs[5] * QVector4D(trans_vs[6], 1)

    return finger_pos.toVector3D()

# 補間曲線を考慮した指定フレーム番号の回転値
def calc_rotation_by_complement(frames, bone_name, frameno):
    for bidx, bf in enumerate(frames[bone_name]):
        if bf.frame >= frameno:
            # 前のキーIDXを0に見立てて、その間の補間曲線を埋める
            fillbf = VmdBoneFrame()
            fillbf.name = bf.name
            fillbf.frame = frameno
            # 実際に登録はしない
            fillbf.key = False

            # 指定されたフレーム以降
            prev_bf = frames[bone_name][bidx - 1]

            if prev_bf.rotation != bf.rotation:
                # 回転補間曲線
                rn = calc_interpolate_bezier(bf.complement[48], bf.complement[52], bf.complement[56], bf.complement[60], prev_bf.frame, bf.frame, fillbf.frame)
                fillbf.rotation = QQuaternion.nlerp(prev_bf.rotation, bf.rotation, rn)
                # logger.debug("key: %s, n: %s, rn: %s, r: %s ", k, prev_frame + n, rn, QQuaternion.nlerp(prev_bf.rotation, bf.rotation, rn) )
                # logger.debug("rotation: prev: %s, fill: %s ", prev_bf.rotation.toEulerAngles(), fillbf.rotation.toEulerAngles() )
            else:
                fillbf.rotation = prev_bf.rotation

            return fillbf.rotation

    # 最後まで行っても見つからなければ、最終項目を返す
    return frames[bone_name][-1].rotation


def adjust_center(trace_model, replace_model, bone_name):
    if bone_name in trace_model and bone_name in replace_model and "左足" in trace_model and "左足" in replace_model:
        # 移植元にも移植先にも対象ボーンがある場合
        # 左足付け根のY位置
        leg_y = trace_model["左足"].position.y()
        # センター（もしくはグルーブ）のY位置
        center_y = trace_model[bone_name].position.y()
        # 足のどの辺りにセンターがあるか判定
        ratio_y = center_y / leg_y
        
        # トレース元と同じ比率の位置にセンターを置く
        replace_model[bone_name].len = replace_model["左足"].position.y() * ratio_y

def compare_length(trace_model, replace_model):
    lengths = {}

    for k, v in replace_model.items():
        # 移植先モデルのボーン構造チェック
        if k in trace_model:
            # 同じ項目がトレース元にもある場合
            trace_bone_length = trace_model[k].len
            replace_bone_length = replace_model[k].len

            # 0割対策を入れて、倍率取得
            length = replace_bone_length if trace_bone_length == 0 else replace_bone_length / trace_bone_length

            # length.setX(length.x() if np.isnan(length.x()) == False and np.isinf(length.x()) == False else 0)
            # length.setY(length.y() if np.isnan(length.y()) == False and np.isinf(length.y()) == False else 0)
            # length.setZ(length.z() if np.isnan(length.z()) == False and np.isinf(length.z()) == False else 0)
            logger.info("bone: %s, trace: %s, replace: %s, length: %s", k, trace_bone_length, replace_bone_length, length)

            lengths[k] = length
    
    return lengths

# 頂点構造を展開する
def load_model_vertexs(replace_model, vertex_path):
    if not os.path.exists(vertex_path):
        return None

    # キー：, 値：ボーンデータ
    vertexs = []
    # 肩より上の頂点リストを生成する
    shoulder_y = 0 if "左肩" not in replace_model else replace_model["左肩"].position.y()

    # ボーンファイルを開く
    with open(vertex_path, "r", encoding=get_file_encoding(vertex_path)) as bf:
        reader = csv.reader(bf)

        for row in reader:
            if row[0] == "Vertex":
                v = QVector3D(float(row[2]), float(row[3]), float(row[4]))

                if v.y() > shoulder_y:
                    vertexs.append(v)

    logger.debug("vertexs: %s", len(vertexs))

    # x -> z -> y の昇順で並び替える
    vertexs = sorted(vertexs, key=lambda u: (u.x(), u.z(), u.y())) 

    return vertexs


# モデルボーン構造を解析する
def load_model_bones(bone_path):
    # キー：ボーン名, 値：ボーンデータ
    bones = {}

    # ボーンファイルを開く
    with open(bone_path, "r", encoding=get_file_encoding(bone_path)) as bf:
        reader = csv.reader(bf)

        for row in reader:
            if row[0] == "IKLink":
                # IKリンク行
                if row[1] in bones:
                    bones[row[1]].links.append(row[2])
                else:
                    logger.warn("IKボーンなし: %s", row[1])
            elif row[0] == "Bone":
                # 通常ボーン行                 
                bone = ModelBone()
                bone.name = row[1]
                bone.parent = row[13]
                bone.position = QVector3D(float(row[5]), float(row[6]), float(row[7]))

                bones[bone.name] = bone
    
    for k, v in bones.items():
        if "ＩＫ" in k:
            # IKの場合、リンクボーンの離れている方を採用する
            farer_pos = QVector3D(0,0,0)
            for l in v.links:
                if l in bones and farer_pos.length() < bones[l].position.length():
                    # 存在するボーンで、大きい方を採用
                    farer_pos = bones[l].position
            # 最も大きな値（離れている）のを採用
            v.len = (v.position - farer_pos).length()
        elif k == "グルーブ" or k == "センター":
            # 親がグルーブの場合、センターとの連動は行わない
            v.len = v.position.length()
        else:
            # IK以外の場合、親ボーンとの間の長さを「親ボーン」に設定する
            if v.parent is not None and v.parent in bones and v.parent != "グルーブ" and v.parent != "センター":
                # 親ボーンを採用
                pos = v.position - bones[v.parent].position
                if v.len > 0:
                    # 既にある場合、平均値を求めて設定する
                    bones[v.parent].len = (v.len + pos.length()) / 2
                else:
                    # 0の場合はそのまま追加
                    bones[v.parent].len = pos.length()
            else:
                # 自分が最親の場合、そのまま長さ
                v.len = v.position.length()

    return bones


# ファイルのエンコードを取得する
def get_file_encoding(file_path):

    try: 
        f = open(file_path, "rb")
        fbytes = f.read()
        f.close()
    except:
        raise Exception("unknown encoding!")
        
    codelst = ('utf_8', 'shift-jis')
    
    for encoding in codelst:
        try:
            fstr = fbytes.decode(encoding) # bytes文字列から指定文字コードの文字列に変換
            fstr = fstr.encode('utf-8') # uft-8文字列に変換
            # 問題なく変換できたらエンコードを返す
            logger.debug("%s: encoding: %s", file_path, encoding)
            return encoding
        except:
            pass
            
    raise Exception("unknown encoding!")
    
if __name__=="__main__":
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--vmd_path', dest='vmd_path', help='input vmd', type=str)
    parser.add_argument('--trace_bone_path', dest='trace_bone_path', help='input trace bone csv', type=str)
    parser.add_argument('--replace_bone_path', dest='replace_bone_path', help='replace trace bone csv', type=str)
    parser.add_argument('--replace_vertex_path', dest='replace_vertex_path', help='replace trace vertex csv', type=str)
    parser.add_argument('--verbose', dest='verbose', help='verbose', type=int)
    args = parser.parse_args()

    logger.setLevel(level[args.verbose])

    main(args.vmd_path, args.trace_bone_path, args.replace_bone_path, args.replace_vertex_path)