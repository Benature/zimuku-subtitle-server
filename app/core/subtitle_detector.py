import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .subtitle_languages import SUBTITLE_LANGUAGE_BY_CODE

# 二进制图形字幕扩展名
BINARY_SUBTITLE_EXTENSIONS = {".sup"}

# 尝试解码的编码列表
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16", "latin-1")

# 常见典型繁体汉字特征样本集
TRADITIONAL_INDICATORS = set(
    "體國點麼聽與變歡廣學華機關開發進實東經長現頭氣風書車動門電區萬問對話邊無說時樣過還後點會"
    "見為來麼個這們雙認說讀寫專視聽藝護類態豐傳圖報辦處規認講質應標歷導創積劃極優響"
)

# 文件名中的常见语言标识映射
FILENAME_LANGUAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(zh-cn-en|chs&eng|chs\.eng|简英|双语|bilingual)\b"), "zh-CN-en"),
    (re.compile(r"(?i)\b(zh-tw-en|cht&eng|cht\.eng|繁英)\b"), "zh-TW-en"),
    (re.compile(r"(?i)\b(zh-cn|chs|chi|sc|gb|简体|简中)\b"), "zh-CN"),
    (re.compile(r"(?i)\b(zh-tw|zh-hk|cht|tc|big5|繁体|繁中)\b"), "zh-TW"),
    (re.compile(r"(?i)\b(en|eng|english|英文|英语)\b"), "en"),
]


@dataclass(frozen=True)
class LanguageAnalysisResult:
    detected_language: str
    detected_language_name: str
    is_bilingual: bool
    encoding: str
    total_dialogues: int
    chinese_char_count: int
    english_word_count: int
    bilingual_dialogue_count: int
    sample_dialogues: list[str]
    confidence: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubtitleDetector:
    """字幕内容解析与语言检测引擎。"""

    @classmethod
    def infer_language_from_filename(cls, filename: str) -> str | None:
        """从文件名中推断预设的语言标签。"""
        stem = Path(filename).stem
        for pattern, lang_code in FILENAME_LANGUAGE_PATTERNS:
            if pattern.search(stem):
                return lang_code
        return None

    @classmethod
    def decode_subtitle_bytes(cls, raw_bytes: bytes) -> tuple[str, str]:
        """将字幕原始二进制数据解码为文本，返回 (解码文本, 编码名称)。"""
        if b"\x00" in raw_bytes[:100] and not raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            # 如果存在大量 NUL 字节且非 UTF-16 BOM，则可能是二进制图形字幕
            if raw_bytes.count(b"\x00") > len(raw_bytes) * 0.1:
                raise ValueError("检测到二进制图形字幕内容，无法直接解码为纯文本")

        for encoding in TEXT_ENCODINGS:
            try:
                text = raw_bytes.decode(encoding)
                return text, encoding
            except (UnicodeDecodeError, ValueError):
                continue

        raise ValueError("无法识别该字幕文件的字符编码")

    @classmethod
    def extract_dialogues(cls, content: str, extension: str) -> list[str]:
        """根据字幕格式解析并提取纯净的对白文本列表。"""
        ext = extension.lower()
        if ext in {".ass", ".ssa"}:
            return cls._extract_ass_dialogues(content)
        if ext in {".srt", ".vtt"}:
            return cls._extract_srt_or_vtt_dialogues(content)
        return cls._extract_generic_text_lines(content)

    @classmethod
    def analyze_dialogues(
        cls,
        dialogues: list[str],
        encoding: str = "utf-8",
        filename_hint: str | None = None,
    ) -> LanguageAnalysisResult:
        """分析对白列表的语言构成并判定是否为双语字幕。"""
        if not dialogues:
            return LanguageAnalysisResult(
                detected_language="unknown",
                detected_language_name="未知",
                is_bilingual=False,
                encoding=encoding,
                total_dialogues=0,
                chinese_char_count=0,
                english_word_count=0,
                bilingual_dialogue_count=0,
                sample_dialogues=[],
                confidence=0.0,
                details={"reason": "无有效对白内容"},
            )

        cjk_regex = re.compile(r"[\u4e00-\u9fff]")
        latin_word_regex = re.compile(r"\b[a-zA-Z]{2,}\b")

        total = len(dialogues)
        bilingual_count = 0
        cjk_lines_count = 0
        latin_lines_count = 0

        total_cjk_chars = 0
        total_latin_words = 0
        traditional_char_count = 0

        bilingual_samples: list[str] = []
        general_samples: list[str] = []

        for line in dialogues:
            cjk_matches = cjk_regex.findall(line)
            latin_matches = latin_word_regex.findall(line)

            has_cjk = len(cjk_matches) > 0
            has_latin = len(latin_matches) >= 1

            total_cjk_chars += len(cjk_matches)
            total_latin_words += len(latin_matches)

            for char in cjk_matches:
                if char in TRADITIONAL_INDICATORS:
                    traditional_char_count += 1

            if has_cjk:
                cjk_lines_count += 1
            if has_latin:
                latin_lines_count += 1

            if has_cjk and has_latin:
                bilingual_count += 1
                if len(bilingual_samples) < 5:
                    bilingual_samples.append(line.strip())
            elif len(general_samples) < 5 and (has_cjk or has_latin):
                general_samples.append(line.strip())

        bilingual_ratio = bilingual_count / total if total > 0 else 0.0
        cjk_ratio = cjk_lines_count / total if total > 0 else 0.0
        latin_ratio = latin_lines_count / total if total > 0 else 0.0

        # 双语判定逻辑
        is_bilingual = False
        # 条件1：单句内同时包含中英文的比例达到 15% 以上（若样本较少则满足至少1句双语且占比>=30%），且中英文字符充足
        if (bilingual_ratio >= 0.15 and total_cjk_chars >= 15 and total_latin_words >= 10) or (
            bilingual_count >= 1 and bilingual_ratio >= 0.3 and total_cjk_chars >= 5 and total_latin_words >= 3
        ):
            is_bilingual = True
        # 条件2：中英双语交替出现（如中文行和英文行分别占用显著行数）
        elif cjk_ratio >= 0.2 and latin_ratio >= 0.2 and total_cjk_chars >= 15 and total_latin_words >= 10:
            is_bilingual = True

        # 判断繁简
        is_traditional = False
        if total_cjk_chars > 0 and traditional_char_count >= 5:
            if (traditional_char_count / max(total_cjk_chars, 1)) >= 0.03:
                is_traditional = True

        samples = bilingual_samples if is_bilingual else (general_samples or dialogues[:5])

        if is_bilingual:
            detected_lang = "zh-CN-en"
            confidence = min(0.99, max(0.8, bilingual_ratio + 0.2))
        elif total_cjk_chars >= 8 and total_cjk_chars >= total_latin_words * 0.5:
            detected_lang = "zh-TW" if is_traditional else "zh-CN"
            confidence = min(0.95, cjk_ratio)
        elif total_latin_words >= 10 and total_cjk_chars < 5:
            detected_lang = "en"
            confidence = min(0.95, latin_ratio)
        else:
            # 参考文件名提示
            hint = cls.infer_language_from_filename(filename_hint) if filename_hint else None
            if hint:
                detected_lang = hint
                confidence = 0.6
            else:
                detected_lang = "unknown"
                confidence = 0.2

        lang_def = SUBTITLE_LANGUAGE_BY_CODE.get(detected_lang)
        detected_name = lang_def.display_name if lang_def else detected_lang

        return LanguageAnalysisResult(
            detected_language=detected_lang,
            detected_language_name=detected_name,
            is_bilingual=is_bilingual,
            encoding=encoding,
            total_dialogues=total,
            chinese_char_count=total_cjk_chars,
            english_word_count=total_latin_words,
            bilingual_dialogue_count=bilingual_count,
            sample_dialogues=samples,
            confidence=round(confidence, 2),
            details={
                "bilingual_ratio": round(bilingual_ratio, 3),
                "chinese_line_ratio": round(cjk_ratio, 3),
                "english_line_ratio": round(latin_ratio, 3),
                "traditional_indicator_count": traditional_char_count,
                "is_traditional": is_traditional,
            },
        )

    @classmethod
    def analyze_file(
        cls,
        file_path: Path,
        max_bytes_to_read: int = 256 * 1024,
    ) -> LanguageAnalysisResult:
        """读取并分析字幕文件的实际语言。"""
        if not file_path.is_file():
            raise FileNotFoundError(f"字幕文件不存在: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix in BINARY_SUBTITLE_EXTENSIONS:
            hint = cls.infer_language_from_filename(file_path.name) or "unknown"
            lang_def = SUBTITLE_LANGUAGE_BY_CODE.get(hint)
            name = lang_def.display_name if lang_def else "图形字幕"
            return LanguageAnalysisResult(
                detected_language=hint,
                detected_language_name=name,
                is_bilingual=hint in {"zh-CN-en", "zh-TW-en"},
                encoding="binary",
                total_dialogues=0,
                chinese_char_count=0,
                english_word_count=0,
                bilingual_dialogue_count=0,
                sample_dialogues=[],
                confidence=0.5 if hint != "unknown" else 0.0,
                details={"is_binary": True, "format": suffix},
            )

        with file_path.open("rb") as f:
            raw_data = f.read(max_bytes_to_read)

        text, encoding = cls.decode_subtitle_bytes(raw_data)
        dialogues = cls.extract_dialogues(text, suffix)
        return cls.analyze_dialogues(dialogues, encoding=encoding, filename_hint=file_path.name)

    @classmethod
    def _extract_ass_dialogues(cls, content: str) -> list[str]:
        """从 ASS/SSA 文件中提取对白。"""
        dialogues: list[str] = []
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("Dialogue:"):
                continue

            # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue

            raw_text = parts[9]
            # 移除 ASS 样式代码，如 {\pos(100,200)}
            clean_text = re.sub(r"\{[^}]*\}", "", raw_text)
            # 替换 ASS 换行符
            clean_text = clean_text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
            clean_text = clean_text.strip()
            if clean_text:
                dialogues.append(clean_text)
        return dialogues

    @classmethod
    def _extract_srt_or_vtt_dialogues(cls, content: str) -> list[str]:
        """从 SRT 或 VTT 文件中提取对白。"""
        dialogues: list[str] = []
        blocks = re.split(r"\r?\n\r?\n", content.strip())

        # 时间轴正则：00:00:01,000 --> 00:00:04,000 或 00:01.000 --> 00:04.000
        timing_pattern = re.compile(r"\d{1,2}:\d{2}.*-->.*\d{1,2}:\d{2}")
        html_tag_pattern = re.compile(r"<[^>]+>")

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            dialogue_lines: list[str] = []
            for line in lines:
                if line.startswith("WEBVTT") or line.startswith("NOTE"):
                    continue
                if line.isdigit():
                    continue
                if timing_pattern.search(line):
                    continue

                cleaned_line = html_tag_pattern.sub("", line).strip()
                if cleaned_line:
                    dialogue_lines.append(cleaned_line)

            if dialogue_lines:
                dialogues.append("\n".join(dialogue_lines))

        return dialogues

    @classmethod
    def _extract_generic_text_lines(cls, content: str) -> list[str]:
        """通用纯文本对白提取。"""
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                lines.append(line)
        return lines
