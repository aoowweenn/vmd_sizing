#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
import re
import logging
import traceback
import argparse
import os.path
import sys
from datetime import datetime

from VmdWriter import VmdWriter, VmdBoneFrame
from VmdReader import VmdReader
import wrapperutils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main(vmd_path):

    try:
        # VMD読み込み
        motion = VmdReader().read_vmd_file(vmd_path)

        if len(motion.frames.values()) > 0:
            # ボーン出力
            bone_fpath = re.sub(r'\.vmd$', "_bone_{0:%Y%m%d_%H%M%S}.csv".format(datetime.now()), vmd_path)
            with open(bone_fpath, encoding='cp932', mode='w') as f:
                
                s = "ボーン名,フレーム,位置X,位置Y,位置Z,回転X,回転Y,回転Z,【X_x1】,Y_x1,Z_x1,R_x1,【X_y1】,Y_y1,Z_y1,R_y1,【X_x2】,Y_x2,Z_x2,R_x2,【X_y2】,Y_y2,Z_y2,R_y2,【Y_x1】,Z_x1,R_x1,X_y1,【Y_y1】,Z_y1,R_y1,X_x2,【Y_x2】,Z_x2,R_x2,X_y2,【Y_y2】,Z_y2,R_y2,1,【Z_x1】,R_x1,X_y1,Y_y1,【Z_y1】,R_y1,X_x2,Y_x2,【Z_x2】,R_x2,X_y2,Y_y2,【Z_y2】,R_y2,1,0,【R_x1】,X_y1,Y_y1,Z_y1,【R_y1】,X_x2,Y_x2,Z_x2,【R_x2】,X_y2,Y_y2,Z_y2,【R_y2】,01,00,00"
                f.write(s)
                f.write("\n")

                for bf_list in motion.frames.values():
                    for bf in bf_list:
                        s = "{0},{1},{2},{3},{4},{5},{6},{7},{8}".format(bf.format_name.encode('cp932', errors='replace').decode(encoding='cp932', errors='replace'), bf.frame, bf.position.x(), bf.position.y(), bf.position.z(), bf.rotation.toEulerAngles().x(), bf.rotation.toEulerAngles().y()*-1, bf.rotation.toEulerAngles().z()*-1,','.join([str(i) for i in bf.complement]))
                        f.write(s)
                        f.write("\n")

            print("ボーンCSV出力成功: %s" % bone_fpath)

        if len(motion.morphs.values()) > 0:
            # モーフ出力
            morph_fpath = re.sub(r'\.vmd$', "_morph_{0:%Y%m%d_%H%M%S}.csv".format(datetime.now()), vmd_path)
            with open(morph_fpath, encoding='cp932', mode='w') as f:
                
                s = "モーフ名,フレーム,大きさ"
                f.write(s)
                f.write("\n")

                for mf_list in motion.morphs.values():
                    for mf in mf_list:
                        s = "{0},{1},{2}".format(mf.format_name.encode('cp932', errors='replace').decode(encoding='cp932', errors='replace'), mf.frame, mf.ratio)
                        f.write(s)
                        f.write("\n")

            print("モーフCSV出力成功: %s" % morph_fpath)

        if len(motion.cameras) > 0:
            # カメラ出力
            camera_fpath = re.sub(r'\.vmd$', "_camera_{0:%Y%m%d_%H%M%S}.csv".format(datetime.now()), vmd_path)
            with open(camera_fpath, encoding='cp932', mode='w') as f:
                
                s = "フレーム,位置X,位置Y,位置Z,回転X,回転Y,回転Z,距離,視野角,パース,X_x1,Y_x1,Z_x1,R_x1,L_x1,VA_x1, X_y1,Y_y1,Z_y1,R_y1,L_y1,VA_y1,X_x2,Y_x2,Z_x2,R_x2,L_x2,VA_x2, X_y2,Y_y2,Z_y2,R_y2,L_y2,VA_y2"
                f.write(s)
                f.write("\n")

                for cf in motion.cameras:
                    s = "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10}".format(cf.frame, cf.position.x(), cf.position.y(), cf.position.z(), cf.euler.x(), cf.euler.y(), cf.euler.z(), -cf.length, cf.angle, cf.perspective,','.join([str(i) for i in cf.complement]))
                    f.write(s)
                    f.write("\n")

            print("カメラCSV出力成功: %s" % camera_fpath)

    except Exception:
        print("■■■■■■■■■■■■■■■■■")
        print("■　**ERROR**　")
        print("■　VMD解析処理が意図せぬエラーで終了しました。")
        print("■■■■■■■■■■■■■■■■■")
        
        print(traceback.format_exc())


if __name__=="__main__":
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--vmd_path', dest='vmd_path', help='input vmd', type=str)
    args = parser.parse_args()

    if wrapperutils.is_valid_file(args.vmd_path, "VMDファイル", ".vmd", True) == False:
        sys.exit(-1)

    main(args.vmd_path)