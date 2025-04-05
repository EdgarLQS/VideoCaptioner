import datetime
import logging
import os
import re
from typing import List

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.config import cfg
from app.core.entities import SynthesisTask
from app.core.utils.logger import setup_logger
from app.core.utils.video_utils import add_subtitles

logger = setup_logger("video_synthesis_thread")

def load_ass_file(file_path: str) -> List[str]:
    """加载 .ass 文件内容"""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.readlines()

def save_ass_file(file_path: str, lines: List[str]):
    """保存 .ass 文件内容"""
    with open(file_path, 'w', encoding='utf-8') as file:
        file.writelines(lines)

def add_third_style(lines: List[str]) -> List[str]:
    """添加 Third 样式到样式部分"""
    for i, line in enumerate(lines):
        if line.startswith("[V4+ Styles]"):
            # 在样式部分插入 Third 样式
            third_style = "Style: Third,方正黑体简体,30,&H0000FF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0.4,0,1,2.0,0,2,10,10,22,1\n"
            lines.insert(i + 2, third_style)
            break
    return lines

def mark_words(lines: List[str], marked_words: List[str]) -> List[str]:
    """将标记的单词单独列出来，并在原文中标记为红色"""
    new_lines = []
    marked_word_set = set()  # 用于记录已经处理过的单词
    for line in lines:
        if line.startswith("Dialogue:"):
            # 匹配 Dialogue 行
            parts = re.split(r",\s*", line.strip(), maxsplit=9)
            if len(parts) == 10:
                style, text = parts[3], parts[9]
                # 检查文本中是否包含标记的单词
                for word, translation in marked_words:
                    # 使用正则表达式进行整词匹配（不区分大小写）
                    pattern = re.compile(rf'\b{word}\b')
                    if pattern.search(text):
                        if word not in marked_word_set:
                            # 插入新行显示标记的单词和翻译，用 ----- 包裹
                            new_line = f"Dialogue: 0,{parts[1]},{parts[2]},Third,,0,0,0,,-> {word} [{translation}] <-\n"
                            new_lines.append(new_line)
                            marked_word_set.add(word)  # 记录已经处理过的单词
                        # 在原文中标记单词为红色
                        text = pattern.sub(rf'{{\\c&H0000FF&}}{word}{{\\r}}', text)
                # 更新原文行
                parts[9] = text
                line = f"Dialogue: {','.join(parts)}\n"
        # 直接将原始行添加到新列表中，确保原文显示
        new_lines.append(line)
    return new_lines

def load_txt_file(file_path: str) -> List[str]:
    """加载 .txt 文件内容"""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.readlines()
def parse_words(lines: List[str]) -> List[tuple]:
    """解析单词及其释义"""
    marked_words = []
    for line in lines:
        # 按空格分割，取第一个部分（单词和音标）和后面的释义
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            word_phonetic, definition = parts
            # 去掉音标部分（任何以方括号包含的内容）
            word = re.sub(r'\s*\[.*?\]', '', word_phonetic).strip()
            # 添加到 marked_words
            marked_words.append((word, definition))
    return marked_words


def convert_to_triple_subtitles(subtitle_file: str) -> str:
    """Convert subtitle file to triple subtitles with CET6 words."""
    # 六级单词文件
    CET6_input_file_txt = "SourceFile\\CET6_edited_clean.txt"
    # 加载 .txt 文件
    CET6_lines = load_txt_file(CET6_input_file_txt)
    # 解析单词及其释义
    CET6_marked_words = parse_words(CET6_lines)

    # 输入文件路径 默认定义翻译后的字幕文件名
    ass_output_file = "modified_subtitle_sample.ass"
    # 获取视频所在的文件夹路径
    video_dir = os.path.dirname(subtitle_file)
    # 拼接输出文件路径
    ass_output_path = os.path.join(video_dir, ass_output_file)
    # 加载原始原始字幕文件ass
    lines = load_ass_file(subtitle_file)
    # 添加 Third 样式【六级词汇】
    lines = add_third_style(lines)
    # 标记单词并插入新行
    lines = mark_words(lines, CET6_marked_words)
    # 保存修改后的文件
    save_ass_file(ass_output_path, lines)

    return ass_output_path

class VideoSynthesisThread(QThread):
    finished = pyqtSignal(SynthesisTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, task: SynthesisTask):
        super().__init__()
        self.task = task
        logger.debug(f"初始化 VideoSynthesisThread，任务: {self.task}")

    def run(self):
        try:
            logger.info(f"\n===========视频合成任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")
            video_file = self.task.video_path
            subtitle_file = self.task.subtitle_path
            output_path = self.task.output_path
            soft_subtitle = self.task.synthesis_config.soft_subtitle
            need_video = self.task.synthesis_config.need_video

            if not need_video:
                logger.info(f"不需要合成视频，跳过")
                self.progress.emit(100, self.tr("合成完成"))
                self.finished.emit(self.task)
                return

            logger.info(f"开始合成视频: {video_file}")
            self.progress.emit(5, self.tr("正在合成"))

            # 调用转换字幕文件的函数
            ass_output_path = convert_to_triple_subtitles(subtitle_file)

            add_subtitles(
                video_file,
                ass_output_path,
                output_path,
                soft_subtitle=soft_subtitle,
                progress_callback=self.progress_callback,
            )

            self.progress.emit(100, self.tr("合成完成"))
            logger.info(f"视频合成完成，保存路径: {output_path}")

            self.finished.emit(self.task)
        except Exception as e:
            logger.exception(f"视频合成失败: {e}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("视频合成失败"))

    def progress_callback(self, value, message):
        progress = int(5 + int(value) / 100 * 95)
        logger.debug(f"合成进度: {progress}% - {message}")
        self.progress.emit(progress, str(progress) + "% " + message)
