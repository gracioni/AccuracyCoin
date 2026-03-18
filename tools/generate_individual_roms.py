from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASM_PATH = ROOT / "AccuracyCoin.asm"
ASSEMBLER_PATH = ROOT / "nesasm.exe"
OUTPUT_DIR = ROOT / "generated_roms" / "individual"
TEMP_ASM_PATH = ROOT / "_single_test_build.asm"
TEMP_NES_PATH = ROOT / "_single_test_build.nes"


TABLE_RE = re.compile(
    r'^(?P<indent>\s*)table\s+"(?P<name>[^"]+)",\s+\$FF,\s+(?P<result>[^,]+),\s+(?P<exec>[A-Za-z0-9_]+)\s*$',
    re.MULTILINE,
)

SUITE_RE = re.compile(
    r"^(?P<label>Suite_[A-Za-z0-9_]+):\s*\r?\n"
    r'\s*\.byte\s+"(?P<title>[^"]+)",\s+\$FF\s*\r?\n'
    r"(?P<body>.*?)(?=^\s*\.byte\s+\$FF\s*$)",
    re.MULTILINE | re.DOTALL,
)

TABLE_TABLE_RE = re.compile(r"^\s*\.word\s+(Suite_[A-Za-z0-9_]+)\s*$", re.MULTILINE)
RELOAD_MAIN_MENU_RE = re.compile(r"ReloadMainMenu:.*?(?=^VerifyJSRBehavior:)", re.MULTILINE | re.DOTALL)
NMI_ROUTINE_RE = re.compile(r"NMI_Routine:.*?(?=^SetUpSuitePointer:)", re.MULTILINE | re.DOTALL)


@dataclass
class TestEntry:
    global_index: int
    page_index: int
    page_number: int
    suite_label: str
    suite_title: str
    test_index: int
    test_name: str
    result_symbol: str
    exec_symbol: str

    @property
    def slug(self) -> str:
        raw = self.test_file_stem
        sanitized = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
        return sanitized.lower()

    @property
    def page_dir_name(self) -> str:
        return sanitize_path_component(f"{self.page_number:02d}-{self.suite_title}")

    @property
    def test_file_stem(self) -> str:
        return sanitize_path_component(f"{self.test_index + 1:02d}-{self.test_name}")

    @property
    def rom_name(self) -> str:
        return f"{self.test_file_stem}.nes"

    @property
    def output_rel_path(self) -> Path:
        return Path(self.page_dir_name) / self.rom_name


def sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]+', "-", value)
    sanitized = re.sub(r"\s+", "-", sanitized.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    sanitized = sanitized.strip("-.")
    return sanitized or "unnamed"


def parse_test_entries(source: str) -> list[TestEntry]:
    table_table_match = re.search(r"TableTable:\s*(?P<body>.*?)^\s*EndTableTable:", source, re.MULTILINE | re.DOTALL)
    if not table_table_match:
        raise RuntimeError("Could not find TableTable in AccuracyCoin.asm")

    ordered_suites = TABLE_TABLE_RE.findall(table_table_match.group("body"))
    if not ordered_suites:
        raise RuntimeError("Could not parse suite order from TableTable")

    suites: dict[str, tuple[str, list[tuple[str, str, str]]]] = {}
    for suite_match in SUITE_RE.finditer(source):
        label = suite_match.group("label")
        title = suite_match.group("title")
        body = suite_match.group("body")
        tests = [
            (
                table_match.group("name"),
                table_match.group("result").strip(),
                table_match.group("exec").strip(),
            )
            for table_match in TABLE_RE.finditer(body)
        ]
        suites[label] = (title, tests)

    entries: list[TestEntry] = []
    global_index = 0
    for page_index, suite_label in enumerate(ordered_suites):
        if suite_label not in suites:
            raise RuntimeError(f"Suite {suite_label} exists in TableTable but was not parsed")
        suite_title, tests = suites[suite_label]
        for test_index, (test_name, result_symbol, exec_symbol) in enumerate(tests):
            global_index += 1
            entries.append(
                TestEntry(
                    global_index=global_index,
                    page_index=page_index,
                    page_number=page_index + 1,
                    suite_label=suite_label,
                    suite_title=suite_title,
                    test_index=test_index,
                    test_name=test_name,
                    result_symbol=result_symbol,
                    exec_symbol=exec_symbol,
                )
            )
    return entries


def build_source_for_test(original_source: str, entry: TestEntry) -> str:
    boot_replacement = """ReloadMainMenu:
\tJSR RunIndividualRom
InfiniteLoop:
\tJMP InfiniteLoop
;;;;;;;

"""
    source, count = RELOAD_MAIN_MENU_RE.subn(boot_replacement, original_source, count=1)
    if count != 1:
        raise RuntimeError("Could not replace ReloadMainMenu block in AccuracyCoin.asm")

    nmi_replacement = f"""NMI_Routine:
\tRTI
;;;;;;;

RunIndividualRom:
\tJSR DisableNMI
\tJSR DisableRendering
\tLDA #0
\tSTA <RunningAllTests
\tSTA <AutomateTestSuite
\tSTA <HighlightTextPrinted
\tSTA <DebugMode
\tSTA <dontSetPointer
\tSTA <PPUCTRL_COPY
\tSTA <PPUMASK_COPY
\tLDA #$80
\tSTA $6000
\tLDA #$DE
\tSTA $6001
\tLDA #$B0
\tSTA $6002
\tLDA #$61
\tSTA $6003
\tLDA #0
\tSTA $6004
\tJSR ClearPage2
\tLDA #$02
\tSTA $4014
\tJSR SetUpNMIRoutineForMainMenu
\tJSR WaitForVBlank
\tJSR TEST_VblankSync_PreTest
\tJSR DMASync
\tLDA #$FF
\tSTA <menuCursorYPos
\tLDA #${entry.page_index:02X}
\tSTA <menuTabXPos
\tJSR SetUpSuitePointer
\tJSR LoadSuiteMenu
\tJSR DrawPageNumber
\tJSR WaitForVBlank
\tJSR ResetScroll
\tJSR EnableFullRendering
\tJSR EnableNMI
\tJSR ReadController1
\tJSR MaskDpadConflicts
\tLDA #${entry.test_index:02X}
\tSTA <menuCursorYPos
\tJSR RunTest
\tJSR DisableNMI
\tJSR BuildSTStatusString
\tJSR DrawSTStatusScreen
\tRTS
;;;;;;;

BuildSTStatusString:
\tLDX <menuCursorYPos
\tTXA
\tASL A
\tTAX
\tLDA <suitePointerList,X
\tSTA <TestResultPointer
\tLDA <suitePointerList+1,X
\tSTA <TestResultPointer+1
\tLDY #0
\tLDA [TestResultPointer],Y
\tSTA <$50
\tAND #$03
\tCMP #$01
\tBEQ BuildSTStatusString_Passed
BuildSTStatusString_Failed:
\tLDA <$50
\tAND #$FC
\tLSR A
\tLSR A
\tTAX
\tBNE BuildSTStatusString_FailedStatusReady
\tLDA #$01
\tSTA $6000
\tBNE BuildSTStatusString_FailedText
BuildSTStatusString_FailedStatusReady:
\tSTA $6000
BuildSTStatusString_FailedText:
\tLDA #$46
\tSTA $6004
\tLDA #$61
\tSTA $6005
\tLDA #$69
\tSTA $6006
\tLDA #$6C
\tSTA $6007
\tLDA #$65
\tSTA $6008
\tLDA #$64
\tSTA $6009
\tLDA #$20
\tSTA $600A
\tTXA
\tJSR STCodeToAscii
\tSTA $600B
\tLDA #0
\tSTA $600C
\tLDA #$46
\tSTA $500
\tLDA #$61
\tSTA $501
\tLDA #$69
\tSTA $502
\tLDA #$6C
\tSTA $503
\tLDA #$65
\tSTA $504
\tLDA #$64
\tSTA $505
\tLDA #$20
\tSTA $506
\tTXA
\tJSR STCodeToAscii
\tSTA $507
\tLDA #0
\tSTA $508
\tRTS
BuildSTStatusString_Passed:
\tLDA #0
\tSTA $6000
\tLDA #$50
\tSTA $6004
\tLDA #$61
\tSTA $6005
\tLDA #$73
\tSTA $6006
\tSTA $6007
\tLDA #$65
\tSTA $6008
\tLDA #$64
\tSTA $6009
\tLDA #0
\tSTA $600A
\tLDA #$50
\tSTA $500
\tLDA #$61
\tSTA $501
\tLDA #$73
\tSTA $502
\tSTA $503
\tLDA #$65
\tSTA $504
\tLDA #$64
\tSTA $505
\tLDA #0
\tSTA $506
\tRTS
;;;;;;;

STCodeToAscii:
\tCMP #$0A
\tBCC STCodeToAscii_Digit
\tCLC
\tADC #$37
\tRTS
STCodeToAscii_Digit:
\tCLC
\tADC #$30
\tRTS
;;;;;;;

DrawSTStatusScreen:
\tLDA #0
\tSTA <DebugMode
\tSTA <PPUCTRL_COPY
\tSTA <PPUMASK_COPY
\tSTA $2000
\tSTA $2001
\tLDA $2002
\tJSR DisableRendering
\tJSR SetUpDefaultPalette
\tJSR ClearNametable
\tLDA #$00
\tSTA <$00
\tLDA #$05
\tSTA <$01
\tLDA #$21
\tSTA <$03
\tLDA #$80
\tSTA <$04
\tJSR PrintNullTextCtr
\tLDA $2002
\tJSR WaitForVBlank
\tJSR ResetScroll
\tJSR EnableRendering_BG
\tRTS
;;;;;;;

PrintNullTextCtr:
\tSTA <Copy_A
\tSTY <Copy_Y
\tSTX <Copy_X
\tLDA $2002
\tLDY #0
PNTC_GetLen:
\tLDA [$0000],Y
\tBEQ PNTC_HaveLen
\tINY
\tBNE PNTC_GetLen
PNTC_HaveLen:
\tLDA <$04
\tAND #$E0
\tORA #$10
\tSTA <$04
\tTYA
\tLSR A
\tEOR #$FF
\tCLC
\tADC #$01
\tCLC
\tADC <$04
\tSTA <$04
\tLDA <$03
\tSTA $2006
\tLDA <$04
\tSTA $2006
\tLDY #0
PNTC_Loop:
\tLDA [$0000],Y
\tBEQ PNTC_Done
\tTAX
\tLDA AsciiToCHR-32,X
\tSTA $2007
\tINY
\tBNE PNTC_Loop
PNTC_Done:
\tLDY <Copy_Y
\tLDX <Copy_X
\tLDA <Copy_A
\tRTS
;;;;;;;

"""
    source, count = NMI_ROUTINE_RE.subn(nmi_replacement, source, count=1)
    if count != 1:
        raise RuntimeError("Could not replace NMI_Routine block in AccuracyCoin.asm")
    return source


def compile_rom(source: str, output_path: Path) -> None:
    TEMP_ASM_PATH.write_text(source, encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [str(ASSEMBLER_PATH), str(TEMP_ASM_PATH.name)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"nesasm failed for {output_path.name}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        if not TEMP_NES_PATH.exists():
            raise RuntimeError(
                f"Expected {TEMP_NES_PATH.name} to be produced for {output_path.name}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        shutil.move(str(TEMP_NES_PATH), str(output_path))
    finally:
        TEMP_ASM_PATH.unlink(missing_ok=True)
        TEMP_NES_PATH.unlink(missing_ok=True)


def write_manifest(entries: list[TestEntry]) -> None:
    manifest_path = OUTPUT_DIR / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "global_index",
                "page_number",
                "page_title",
                "test_index_on_page",
                "test_name",
                "result_symbol",
                "exec_symbol",
                "page_dir",
                "rom_name",
                "relative_path",
            ]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.global_index,
                    entry.page_number,
                    entry.suite_title,
                    entry.test_index + 1,
                    entry.test_name,
                    entry.result_symbol,
                    entry.exec_symbol,
                    entry.page_dir_name,
                    entry.rom_name,
                    str(entry.output_rel_path),
                ]
            )


def print_usage() -> None:
    script_name = Path(sys.argv[0]).name
    print("Generate individual AccuracyCoin test ROMs.")
    print()
    print("Usage:")
    print(f"  python {script_name} generate")
    print(f"  python {script_name} --help")
    print()
    print("Output:")
    print(f"  {OUTPUT_DIR}")


def generate_roms() -> None:
    original_source = ASM_PATH.read_text(encoding="utf-8")
    entries = parse_test_entries(original_source)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for existing in OUTPUT_DIR.iterdir():
        if existing.is_dir():
            shutil.rmtree(existing)
        elif existing.name.endswith(".nes"):
            existing.unlink()

    for entry in entries:
        output_path = OUTPUT_DIR / entry.output_rel_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        source = build_source_for_test(original_source, entry)
        compile_rom(source, output_path)

    write_manifest(entries)
    print(f"Generated {len(entries)} ROMs in {OUTPUT_DIR}")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help", "help"}:
        print_usage()
        return

    if args[0] == "generate":
        generate_roms()
        return

    print(f"Unknown command: {args[0]}")
    print()
    print_usage()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
