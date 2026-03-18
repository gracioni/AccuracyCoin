; Template injected by tools/generate_individual_roms.py into a temporary copy
; of AccuracyCoin.asm before assembly.
;
; The Python generator replaces these placeholders:
;   __PAGE_INDEX__ -> suite/page index in hexadecimal byte form
;   __TEST_INDEX__ -> test index within the page in hexadecimal byte form
;
; Example:
;   LDA #$__PAGE_INDEX__  -> LDA #$0C
;   LDA #$__TEST_INDEX__  -> LDA #$07

ReloadMainMenu:
	JSR RunIndividualRom
InfiniteLoop:
	JMP InfiniteLoop
;;;;;;;

NMI_Routine:
	RTI
;;;;;;;

RunIndividualRom:
	JSR DisableNMI
	JSR DisableRendering
	LDA #0
	STA <RunningAllTests
	STA <AutomateTestSuite
	STA <HighlightTextPrinted
	STA <DebugMode
	STA <dontSetPointer
	STA <PPUCTRL_COPY
	STA <PPUMASK_COPY
	LDA #$80
	STA $6000
	LDA #$DE
	STA $6001
	LDA #$B0
	STA $6002
	LDA #$61
	STA $6003
	LDA #0
	STA $6004
	JSR ClearPage2
	LDA #$02
	STA $4014
	JSR SetUpNMIRoutineForMainMenu
	JSR WaitForVBlank
	JSR TEST_VblankSync_PreTest
	JSR DMASync
	LDA #$FF
	STA <menuCursorYPos
	LDA #$__PAGE_INDEX__
	STA <menuTabXPos
	JSR SetUpSuitePointer
	JSR LoadSuiteMenu
	JSR DrawPageNumber
	JSR WaitForVBlank
	JSR ResetScroll
	JSR EnableFullRendering
	JSR EnableNMI
	JSR ReadController1
	JSR MaskDpadConflicts
	LDA #$__TEST_INDEX__
	STA <menuCursorYPos
	JSR RunTest
	JSR DisableNMI
	JSR BuildSTStatusString
	JSR DrawSTStatusScreen
	RTS
;;;;;;;

BuildSTStatusString:
	LDX <menuCursorYPos
	TXA
	ASL A
	TAX
	LDA <suitePointerList,X
	STA <TestResultPointer
	LDA <suitePointerList+1,X
	STA <TestResultPointer+1
	LDY #0
	LDA [TestResultPointer],Y
	STA <$50
	AND #$03
	CMP #$01
	BEQ BuildSTStatusString_Passed
BuildSTStatusString_Failed:
	LDA <$50
	AND #$FC
	LSR A
	LSR A
	TAX
	BNE BuildSTStatusString_FailedStatusReady
	LDA #$01
	STA $6000
	BNE BuildSTStatusString_FailedText
BuildSTStatusString_FailedStatusReady:
	STA $6000
BuildSTStatusString_FailedText:
	LDA #$46
	STA $6004
	LDA #$61
	STA $6005
	LDA #$69
	STA $6006
	LDA #$6C
	STA $6007
	LDA #$65
	STA $6008
	LDA #$64
	STA $6009
	LDA #$20
	STA $600A
	TXA
	JSR STCodeToAscii
	STA $600B
	LDA #0
	STA $600C
	LDA #$46
	STA $500
	LDA #$61
	STA $501
	LDA #$69
	STA $502
	LDA #$6C
	STA $503
	LDA #$65
	STA $504
	LDA #$64
	STA $505
	LDA #$20
	STA $506
	TXA
	JSR STCodeToAscii
	STA $507
	LDA #0
	STA $508
	RTS
BuildSTStatusString_Passed:
	LDA #0
	STA $6000
	LDA #$50
	STA $6004
	LDA #$61
	STA $6005
	LDA #$73
	STA $6006
	STA $6007
	LDA #$65
	STA $6008
	LDA #$64
	STA $6009
	LDA #0
	STA $600A
	LDA #$50
	STA $500
	LDA #$61
	STA $501
	LDA #$73
	STA $502
	STA $503
	LDA #$65
	STA $504
	LDA #$64
	STA $505
	LDA #0
	STA $506
	RTS
;;;;;;;

STCodeToAscii:
	CMP #$0A
	BCC STCodeToAscii_Digit
	CLC
	ADC #$37
	RTS
STCodeToAscii_Digit:
	CLC
	ADC #$30
	RTS
;;;;;;;

DrawSTStatusScreen:
	LDA #0
	STA <DebugMode
	STA <PPUCTRL_COPY
	STA <PPUMASK_COPY
	STA $2000
	STA $2001
	LDA $2002
	JSR DisableRendering
	JSR SetUpDefaultPalette
	JSR ClearNametable
	LDA #$00
	STA <$00
	LDA #$05
	STA <$01
	LDA #$21
	STA <$03
	LDA #$80
	STA <$04
	JSR PrintNullTextCtr
	LDA $2002
	JSR WaitForVBlank
	JSR ResetScroll
	JSR EnableRendering_BG
	RTS
;;;;;;;

PrintNullTextCtr:
	STA <Copy_A
	STY <Copy_Y
	STX <Copy_X
	LDA $2002
	LDY #0
PNTC_GetLen:
	LDA [$0000],Y
	BEQ PNTC_HaveLen
	INY
	BNE PNTC_GetLen
PNTC_HaveLen:
	LDA <$04
	AND #$E0
	ORA #$10
	STA <$04
	TYA
	LSR A
	EOR #$FF
	CLC
	ADC #$01
	CLC
	ADC <$04
	STA <$04
	LDA <$03
	STA $2006
	LDA <$04
	STA $2006
	LDY #0
PNTC_Loop:
	LDA [$0000],Y
	BEQ PNTC_Done
	TAX
	LDA AsciiToCHR-32,X
	STA $2007
	INY
	BNE PNTC_Loop
PNTC_Done:
	LDY <Copy_Y
	LDX <Copy_X
	LDA <Copy_A
	RTS
;;;;;;;
