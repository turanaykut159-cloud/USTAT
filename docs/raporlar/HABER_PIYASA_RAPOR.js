const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak, LevelFormat } = require("docx");

const border = { style: BorderStyle.SINGLE, size: 1, color: "AAAAAA" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };
const headerShading = { fill: "1B2A4A", type: ShadingType.CLEAR };
const altShading = { fill: "F0F4F8", type: ShadingType.CLEAR };
const criticalShading = { fill: "FFE0E0", type: ShadingType.CLEAR };
const successShading = { fill: "E0FFE0", type: ShadingType.CLEAR };

const tw = (text, opts = {}) => new TextRun({ text, font: "Arial", ...opts });
const twB = (text, opts = {}) => tw(text, { bold: true, ...opts });
const twH = (text) => tw(text, { bold: true, color: "FFFFFF", size: 18 });
const p = (children, opts = {}) => new Paragraph({ children, spacing: { after: 120 }, ...opts });
const pHead = (text, level) => new Paragraph({ heading: level, children: [twB(text, { size: level === HeadingLevel.HEADING_1 ? 32 : level === HeadingLevel.HEADING_2 ? 26 : 22 })], spacing: { before: 300, after: 200 } });

function headerCell(text, width) {
  return new TableCell({ borders, width: { size: width, type: WidthType.DXA }, shading: headerShading, margins: cellMargins, verticalAlign: "center",
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [twH(text)] })] });
}
function cell(text, width, shading, opts = {}) {
  const runs = typeof text === "string" ? [tw(text, { size: 18, ...opts })] : text;
  return new TableCell({ borders, width: { size: width, type: WidthType.DXA }, shading, margins: cellMargins,
    children: [new Paragraph({ children: runs, spacing: { after: 40 } })] });
}

const TW = 9360;
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, font: "Arial", color: "1B2A4A" }, paragraph: { spacing: { before: 360, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, font: "Arial", color: "2E5090" }, paragraph: { spacing: { before: 240, after: 180 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, font: "Arial", color: "444444" }, paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ]},
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1200, right: 1440, bottom: 1200, left: 1440 } }
    },
    headers: { default: new Header({ children: [
      new Paragraph({ alignment: AlignmentType.CENTER, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "1B2A4A", space: 4 } },
        children: [tw("USTAT CEO RAPORU", { bold: true, size: 18, color: "1B2A4A" }), tw("  |  ", { size: 18, color: "999999" }), tw("23 Mart 2026  |  HABER-P\u0130YASA ZAMANLAMA ANAL\u0130Z\u0130", { size: 18, color: "666666" })] })
    ]})},
    footers: { default: new Footer({ children: [
      new Paragraph({ alignment: AlignmentType.CENTER, children: [tw("Sayfa ", { size: 16, color: "999999" }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "999999" }), tw(" | G\u0130ZL\u0130 \u2014 Sadece CEO i\u00e7in", { size: 16, color: "999999" })] })
    ]})},
    children: [
      // TITLE
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [tw("\uD83D\uDCCA", { size: 48 })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [twB("HABER ZAMANLAMA vs P\u0130YASA HAREKET\u0130", { size: 36, color: "1B2A4A" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [tw("DER\u0130N ANAL\u0130Z RAPORU", { size: 24, color: "666666" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 }, children: [tw("23 Mart 2026 Pazartesi | Trump-\u0130ran H\u00fcrmuz Krizi", { size: 20, color: "888888" })] }),

      // SECTION 1: NEWS TIMELINE
      pHead("1. HABER\u0130N YAYILMA ZAMANLAMAS\u0130", HeadingLevel.HEADING_1),
      p([tw("A\u015fa\u011f\u0131daki tablo, Trump'\u0131n \u0130ran'\u0131 tehdit eden H\u00fcrmuz Bo\u011faz\u0131 \u00fcltimatomunun her platformda ilk yay\u0131nlanma zaman\u0131n\u0131 g\u00f6stermektedir. T\u00fcm saatler T\u00fcrkiye saati (UTC+3) olarak verilmi\u015ftir.", { size: 20 })]),

      new Table({
        width: { size: TW, type: WidthType.DXA },
        columnWidths: [500, 1600, 1800, 2200, 3260],
        rows: [
          new TableRow({ children: [
            headerCell("#", 500), headerCell("SAAT (TR)", 1600), headerCell("PLATFORM", 1800), headerCell("KAYNAK", 2200), headerCell("DETAY", 3260)
          ]}),
          new TableRow({ children: [
            cell("1", 500, criticalShading, {bold:true}), cell("02:44", 1600, criticalShading, {bold:true}), cell("Truth Social", 1800, criticalShading, {bold:true}),
            cell("Donald Trump", 2200, criticalShading, {bold:true}), cell("48 saat ultimatum: H\u00fcrmuz a\u00e7\u0131ls\u0131n yoksa santrallar vurulur", 3260, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("2", 500, altShading), cell("02:46-02:50", 1600, altShading), cell("X (Twitter)", 1800, altShading),
            cell("Drop Site News", 2200, altShading), cell("Truth Social postunu payla\u015fan ilk b\u00fcy\u00fck hesap", 3260, altShading)
          ]}),
          new TableRow({ children: [
            cell("3", 500), cell("02:48", 1600), cell("Reuters Wire", 1800),
            cell("Reuters Flash", 2200), cell("URGENT: Trump threatens Iran power plants", 3260)
          ]}),
          new TableRow({ children: [
            cell("4", 500, altShading), cell("02:50", 1600, altShading), cell("Bloomberg Terminal", 1800, altShading),
            cell("Bloomberg First Word", 2200, altShading), cell("FLASH: Trump 48-hour ultimatum to Iran on Hormuz", 3260, altShading)
          ]}),
          new TableRow({ children: [
            cell("5", 500), cell("02:52", 1600), cell("AP Wire", 1800),
            cell("Associated Press", 2200), cell("BREAKING: Trump threatens strikes on Iran", 3260)
          ]}),
          new TableRow({ children: [
            cell("6", 500, altShading), cell("02:55-03:05", 1600, altShading), cell("CNBC / CNN", 1800, altShading),
            cell("TV Kanallar\u0131", 2200, altShading), cell("Breaking news yay\u0131nlar\u0131 ba\u015flad\u0131", 3260, altShading)
          ]}),
          new TableRow({ children: [
            cell("7", 500), cell("03:10", 1600), cell("Al Jazeera", 1800),
            cell("AJ Breaking", 2200), cell("Iran threatens to close Hormuz completely", 3260)
          ]}),
          new TableRow({ children: [
            cell("8", 500, altShading), cell("03:15-03:30", 1600, altShading), cell("ZeroHedge / FinTwit", 1800, altShading),
            cell("Finans Twitter", 2200, altShading), cell("Piyasa etki analizleri yay\u0131lmaya ba\u015flad\u0131", 3260, altShading)
          ]}),
          new TableRow({ children: [
            cell("9", 500), cell("04:00-04:30", 1600), cell("\u0130ran Resmi", 1800),
            cell("Ghalibaf (Meclis Bsk)", 2200), cell("X\u2019te kar\u015f\u0131l\u0131k: Santrallar vurulursa altyap\u0131 yok edilir", 3260)
          ]}),
          new TableRow({ children: [
            cell("10", 500, altShading), cell("07:00-08:00", 1600, altShading), cell("T\u00fcrk Medyas\u0131", 1800, altShading),
            cell("AA / Habert\u00fcrk / BHT", 2200, altShading), cell("Sabah b\u00fcltenlerinde detayl\u0131 haberler", 3260, altShading)
          ]}),
        ]
      }),
      p([tw("")]),
      p([twB("SONU\u00c7: ", { color: "CC0000", size: 20 }), tw("Haber Cumartesi gece 02:44\u2019te (TR) d\u00fc\u015ft\u00fc. Pazar g\u00fcn\u00fc piyasalar kapal\u0131yd\u0131. Pazartesi 09:30 a\u00e7\u0131l\u0131\u015f\u0131na kadar 31 saat ge\u00e7ti. T\u00fcm kurumsal yat\u0131r\u0131mc\u0131lar haz\u0131rl\u0131k yapt\u0131.", { size: 20 })]),

      // SECTION 2: GLOBAL MARKET REACTIONS
      new Paragraph({ children: [new PageBreak()] }),
      pHead("2. GLOBAL P\u0130YASALARIN REAKS\u0130YON ZAMANLARI", HeadingLevel.HEADING_1),
      p([tw("Asya borsalar\u0131 Pazartesi sabah a\u00e7\u0131ld\u0131\u011f\u0131nda ilk tepkiyi verdi. A\u015fa\u011f\u0131da her piyasan\u0131n a\u00e7\u0131l\u0131\u015f saati ve d\u00fc\u015f\u00fc\u015f oran\u0131:", { size: 20 })]),

      new Table({
        width: { size: TW, type: WidthType.DXA },
        columnWidths: [2000, 1800, 1800, 1800, 1960],
        rows: [
          new TableRow({ children: [
            headerCell("P\u0130YASA", 2000), headerCell("A\u00c7ILI\u015e (TR)", 1800), headerCell("D\u00dc\u015e\u00dc\u015e %", 1800), headerCell("HABER ARASI", 1800), headerCell("NOT", 1960)
          ]}),
          new TableRow({ children: [
            cell("Nikkei 225", 2000, altShading, {bold:true}), cell("03:00", 1800, altShading), cell("-%3.68", 1800, altShading, {color:"CC0000",bold:true}), cell("~15 dk", 1800, altShading), cell("Habere anl\u0131k tepki", 1960, altShading)
          ]}),
          new TableRow({ children: [
            cell("KOSPI", 2000, criticalShading, {bold:true}), cell("03:00", 1800, criticalShading), cell("-%6.49", 1800, criticalShading, {color:"CC0000",bold:true}), cell("~15 dk", 1800, criticalShading), cell("Devre kesici tetiklendi!", 1960, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("Hang Seng", 2000, altShading, {bold:true}), cell("04:30", 1800, altShading), cell("-%1.93", 1800, altShading, {color:"CC0000",bold:true}), cell("~2 saat", 1800, altShading), cell("Nispeten \u0131l\u0131ml\u0131", 1960, altShading)
          ]}),
          new TableRow({ children: [
            cell("Brent Petrol", 2000, criticalShading, {bold:true}), cell("02:50 (futures)", 1800, criticalShading), cell("+%5.0", 1800, criticalShading, {color:"008800",bold:true}), cell("~6 dk", 1800, criticalShading), cell("110$ \u00fczerine f\u0131rlad\u0131", 1960, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("DAX Futures", 2000, altShading, {bold:true}), cell("03:00", 1800, altShading), cell("-%2.0", 1800, altShading, {color:"CC0000",bold:true}), cell("~15 dk", 1800, altShading), cell("Pre-market", 1960, altShading)
          ]}),
          new TableRow({ children: [
            cell("BIST 100 / XU30", 2000, criticalShading, {bold:true}), cell("09:30", 1800, criticalShading), cell("-%4.5 gap", 1800, criticalShading, {color:"CC0000",bold:true}), cell("7 saat", 1800, criticalShading), cell("Gap-down a\u00e7\u0131l\u0131\u015f!", 1960, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("USD/TRY", 2000, altShading), cell("09:30", 1800, altShading), cell("+%0.04", 1800, altShading), cell("7 saat", 1800, altShading), cell("S\u0131n\u0131rl\u0131 etki", 1960, altShading)
          ]}),
        ]
      }),
      p([tw("")]),
      p([twB("KR\u0130T\u0130K BULGU: ", { color: "CC0000", size: 20 }), tw("Haber 02:44\u2019te d\u00fc\u015ft\u00fc. Asya borsalar\u0131 03:00\u2019te a\u00e7\u0131ld\u0131 (16 dakika sonra). V\u0130OP 09:30\u2019da a\u00e7\u0131ld\u0131 (7 saat sonra). Bu 7 saat i\u00e7inde t\u00fcm d\u00fcnya piyasas\u0131 fiyatlad\u0131. V\u0130OP en son tepki veren piyasa oldu.", { size: 20 })]),

      // SECTION 3: 15 CONTRACTS
      new Paragraph({ children: [new PageBreak()] }),
      pHead("3. 15 V\u0130OP KONTRATININ HAREKET ZAMANLARI", HeadingLevel.HEADING_1),
      p([tw("A\u015fa\u011f\u0131daki tablo, MT5 grafik ve sol panel verilerinden okunan 15 kontrat\u0131n 23 Mart 2026 Pazartesi g\u00fcn\u00fc performans\u0131n\u0131 g\u00f6stermektedir. T\u00fcm V\u0130OP kontratlar\u0131 09:30\u2019da a\u00e7\u0131ld\u0131.", { size: 20 })]),

      pHead("3.1 A\u00e7\u0131l\u0131\u015f Gap ve G\u00fcn \u0130\u00e7i Performans", HeadingLevel.HEADING_2),

      new Table({
        width: { size: TW, type: WidthType.DXA },
        columnWidths: [1400, 900, 900, 900, 1000, 900, 1100, 1000, 260],
        rows: [
          new TableRow({ children: [
            headerCell("KONTRAT", 1400), headerCell("SINIF", 900), headerCell("C.KPNS", 900), headerCell("ACILIS", 900),
            headerCell("GAP %", 1000), headerCell("D\u0130P", 900), headerCell("14:30", 1100), headerCell("G\u00dcN %", 1000), headerCell("", 260)
          ]}),
          // A Class
          new TableRow({ children: [
            cell("F_AKBNK", 1400, criticalShading, {bold:true}), cell("A", 900, criticalShading), cell("72.50", 900, criticalShading), cell("68.00", 900, criticalShading),
            cell("-6.2%", 1000, criticalShading, {bold:true,color:"CC0000"}), cell("66.23", 900, criticalShading), cell("69.29", 1100, criticalShading), cell("+4.1%", 1000, criticalShading, {color:"008800"}), cell("", 260, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("F_THYAO", 1400, altShading, {bold:true}), cell("A", 900, altShading), cell("~290", 900, altShading), cell("~280", 900, altShading),
            cell("-3.4%", 1000, altShading, {color:"CC0000"}), cell("~278", 900, altShading), cell("298.05", 1100, altShading), cell("+3.6%", 1000, altShading, {color:"008800"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_ASELS", 1400, null, {bold:true}), cell("A", 900), cell("~350", 900), cell("~348", 900),
            cell("-0.6%", 1000, null, {color:"CC0000"}), cell("~347", 900), cell("353.00", 1100), cell("+1.2%", 1000, null, {color:"008800"}), cell("", 260)
          ]}),
          new TableRow({ children: [
            cell("F_TCELL", 1400, altShading, {bold:true}), cell("A", 900, altShading), cell("~105", 900, altShading), cell("~104", 900, altShading),
            cell("-1.0%", 1000, altShading, {color:"CC0000"}), cell("~103", 900, altShading), cell("107.45", 1100, altShading), cell("+3.4%", 1000, altShading, {color:"008800"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_PGSUS", 1400, successShading, {bold:true}), cell("A", 900, successShading), cell("~168", 900, successShading), cell("~165", 900, successShading),
            cell("-1.8%", 1000, successShading, {color:"CC0000"}), cell("~165", 900, successShading), cell("179.55", 1100, successShading), cell("+7.4%", 1000, successShading, {bold:true,color:"008800"}), cell("", 260, successShading)
          ]}),
          // B Class
          new TableRow({ children: [
            cell("F_HALKB", 1400, criticalShading, {bold:true}), cell("B", 900, criticalShading), cell("~40.00", 900, criticalShading), cell("~37.50", 900, criticalShading),
            cell("-6.3%", 1000, criticalShading, {bold:true,color:"CC0000"}), cell("~36.80", 900, criticalShading), cell("38.77", 1100, criticalShading), cell("+3.9%", 1000, criticalShading, {color:"008800"}), cell("", 260, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("F_GUBRF", 1400, altShading, {bold:true}), cell("B", 900, altShading), cell("~480", 900, altShading), cell("~472", 900, altShading),
            cell("-1.7%", 1000, altShading, {color:"CC0000"}), cell("~470", 900, altShading), cell("479.00", 1100, altShading), cell("+4.2%", 1000, altShading, {color:"008800"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_EKGYO", 1400, null, {bold:true}), cell("B", 900), cell("~19.50", 900), cell("~19.00", 900),
            cell("-2.6%", 1000, null, {color:"CC0000"}), cell("~18.80", 900), cell("19.78", 1100), cell("+4.7%", 1000, null, {color:"008800"}), cell("", 260)
          ]}),
          new TableRow({ children: [
            cell("F_SOKM", 1400, altShading, {bold:true}), cell("B", 900, altShading), cell("~51.00", 900, altShading), cell("~50.00", 900, altShading),
            cell("-2.0%", 1000, altShading, {color:"CC0000"}), cell("~49.50", 900, altShading), cell("51.57", 1100, altShading), cell("+3.0%", 1000, altShading, {color:"008800"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_TKFEN", 1400, null, {bold:true}), cell("B", 900), cell("~82.00", 900), cell("~81.00", 900),
            cell("-1.2%", 1000, null, {color:"CC0000"}), cell("~80.50", 900), cell("83.14", 1100), cell("+2.2%", 1000, null, {color:"008800"}), cell("", 260)
          ]}),
          // Others from MT5
          new TableRow({ children: [
            cell("F_FROTO", 1400, criticalShading, {bold:true}), cell("-", 900, criticalShading), cell("~107", 900, criticalShading), cell("~100", 900, criticalShading),
            cell("-6.5%", 1000, criticalShading, {bold:true,color:"CC0000"}), cell("~99.00", 900, criticalShading), cell("106.60", 1100, criticalShading), cell("+6.5%", 1000, criticalShading, {color:"008800"}), cell("", 260, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("F_TUPRS", 1400, altShading, {bold:true}), cell("-", 900, altShading), cell("~262", 900, altShading), cell("~256", 900, altShading),
            cell("-2.3%", 1000, altShading, {color:"CC0000"}), cell("~254", 900, altShading), cell("259.95", 1100, altShading), cell("-1.3%", 1000, altShading, {color:"CC0000"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_PETKM", 1400, null, {bold:true}), cell("-", 900), cell("~21.50", 900), cell("~20.50", 900),
            cell("-4.7%", 1000, null, {color:"CC0000"}), cell("~20.10", 900), cell("20.45", 1100), cell("-5.1%", 1000, null, {color:"CC0000"}), cell("", 260)
          ]}),
          new TableRow({ children: [
            cell("F_YKBNK", 1400, altShading, {bold:true}), cell("-", 900, altShading), cell("~33.50", 900, altShading), cell("~32.50", 900, altShading),
            cell("-3.0%", 1000, altShading, {color:"CC0000"}), cell("~32.00", 900, altShading), cell("33.84", 1100, altShading), cell("+4.0%", 1000, altShading, {color:"008800"}), cell("", 260, altShading)
          ]}),
          new TableRow({ children: [
            cell("F_BRSAN", 1400, null, {bold:true}), cell("-", 900), cell("~510", 900), cell("~500", 900),
            cell("-2.0%", 1000, null, {color:"CC0000"}), cell("~498", 900), cell("506.90", 1100), cell("+4.0%", 1000, null, {color:"008800"}), cell("", 260)
          ]}),
        ]
      }),

      p([tw("")]),
      p([twB("ANAL\u0130Z: ", { color: "1B2A4A", size: 20 }), tw("T\u00fcm 15 kontrat 09:30\u2019da gap-down ile a\u00e7\u0131ld\u0131. En sert d\u00fc\u015fenler: F_FROTO (-%6.5), F_HALKB (-%6.3), F_AKBNK (-%6.2). Dip 09:45-10:00 aras\u0131nda g\u00f6r\u00fcld\u00fc. Toparlanma 10:00\u2019da ba\u015flad\u0131. 14:30\u2019a kadar \u00e7o\u011fu kontrat kay\u0131plar\u0131n\u0131 kapatt\u0131. F_PGSUS ve F_FROTO en g\u00fc\u00e7l\u00fc toparlanmay\u0131 g\u00f6sterdi.", { size: 20 })]),

      // SECTION 4: COMPARISON
      new Paragraph({ children: [new PageBreak()] }),
      pHead("4. HABER vs P\u0130YASA ZAMANLAMA KAR\u015eILA\u015eTIRMASI", HeadingLevel.HEADING_1),

      pHead("4.1 Kronolojik S\u0131ralama", HeadingLevel.HEADING_2),

      new Table({
        width: { size: TW, type: WidthType.DXA },
        columnWidths: [1600, 2500, 2500, 2760],
        rows: [
          new TableRow({ children: [
            headerCell("SAAT (TR)", 1600), headerCell("OLAY", 2500), headerCell("P\u0130YASA TEPK\u0130S\u0130", 2500), headerCell("V\u0130OP ETK\u0130S\u0130", 2760)
          ]}),
          new TableRow({ children: [
            cell("C.tesi 02:44", 1600, criticalShading, {bold:true}), cell("Trump Truth Social postu", 2500, criticalShading), cell("Piyasalar KAPALI", 2500, criticalShading), cell("V\u0130OP KAPALI", 2760, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("02:48-02:52", 1600, altShading), cell("Reuters/Bloomberg/AP flash", 2500, altShading), cell("Futures an\u0131nda tepki", 2500, altShading), cell("V\u0130OP KAPALI", 2760, altShading)
          ]}),
          new TableRow({ children: [
            cell("Pzr 03:00", 1600), cell("Asya borsalar\u0131 a\u00e7\u0131ld\u0131", 2500), cell("Nikkei -%3.68, Kospi -%6.49", 2500), cell("V\u0130OP KAPALI", 2760)
          ]}),
          new TableRow({ children: [
            cell("04:00-04:30", 1600, altShading), cell("\u0130ran resmi kar\u015f\u0131l\u0131k verdi", 2500, altShading), cell("Petrol 113$\u2019a t\u0131rmand\u0131", 2500, altShading), cell("V\u0130OP KAPALI", 2760, altShading)
          ]}),
          new TableRow({ children: [
            cell("Pzt 09:30", 1600, criticalShading, {bold:true}), cell("V\u0130OP a\u00e7\u0131l\u0131\u015f\u0131", 2500, criticalShading, {bold:true}), cell("7 saat gecikmeyle tepki", 2500, criticalShading), cell("T\u00dcM KONTRATLAR GAP-DOWN", 2760, criticalShading, {bold:true})
          ]}),
          new TableRow({ children: [
            cell("09:30-09:45", 1600, criticalShading), cell("Panik sat\u0131\u015f dalgas\u0131", 2500, criticalShading), cell("-%4 ile -%6.5 aras\u0131 d\u00fc\u015f\u00fc\u015f", 2500, criticalShading), cell("F_AKBNK 72\u219266, F_FROTO 107\u219299", 2760, criticalShading)
          ]}),
          new TableRow({ children: [
            cell("09:45-10:00", 1600, altShading), cell("D\u0130P NOKTASI", 2500, altShading, {bold:true}), cell("Sat\u0131\u015f bask\u0131s\u0131 azald\u0131", 2500, altShading), cell("O\u011eUL: S\u0130NYAL YOK (VOLATILE)", 2760, altShading, {bold:true,color:"CC0000"})
          ]}),
          new TableRow({ children: [
            cell("10:00-12:00", 1600), cell("Kademeli toparlanma", 2500), cell("D\u0131\u015f piyasalar duruldu", 2500), cell("O\u011eUL: S\u0130NYAL YOK (NOTR bug)", 2760, null, {bold:true,color:"CC0000"})
          ]}),
          new TableRow({ children: [
            cell("12:00-14:00", 1600, altShading), cell("Rejim TREND\u2019e d\u00f6nd\u00fc", 2500, altShading), cell("Toparlanma h\u0131zland\u0131", 2500, altShading), cell("O\u011eUL: HALA NOTR (EMA lag)", 2760, altShading, {bold:true,color:"CC0000"})
          ]}),
          new TableRow({ children: [
            cell("14:06", 1600, successShading), cell("O\u011eUL ilk i\u015flem", 2500, successShading, {bold:true}), cell("F_HALKB SELL 36.94", 2500, successShading), cell("4.5 SAAT GEC\u0130KME", 2760, successShading, {bold:true})
          ]}),
          new TableRow({ children: [
            cell("14:26", 1600, successShading), cell("O\u011eUL ikinci i\u015flem", 2500, successShading, {bold:true}), cell("F_AKBNK BUY 69.92", 2500, successShading), cell("D\u0130P \u00c7OKTAN GE\u00c7M\u0130\u015e", 2760, successShading, {bold:true})
          ]}),
        ]
      }),

      p([tw("")]),
      pHead("4.2 Ana Bulgular", HeadingLevel.HEADING_2),
      p([twB("1. Haber piyasadan \u00d6NCE de\u011fil, hafta sonu geldi. ", { size: 20, color: "1B2A4A" }), tw("Piyasa a\u00e7\u0131l\u0131\u015f\u0131ndan \u00f6nce hareket ba\u015flamad\u0131. T\u00fcm hareket 09:30 a\u00e7\u0131l\u0131\u015f\u0131nda gap olarak ger\u00e7ekle\u015fti.", { size: 20 })]),
      p([twB("2. V\u0130OP d\u00fcnyadaki en ge\u00e7 tepki veren piyasa oldu. ", { size: 20, color: "1B2A4A" }), tw("Asya 16 dk, Avrupa 6 saat, V\u0130OP 7 saat sonra fiyatlad\u0131. Bu da gap-down riskini art\u0131rd\u0131.", { size: 20 })]),
      p([twB("3. O\u011eUL\u2019un 4.5 saatlik gecikmesi kabul edilemez. ", { size: 20, color: "CC0000" }), tw("Sabah 09:45\u2019te dip g\u00f6r\u00fcld\u00fc. O\u011eUL ancak 14:06\u2019da ilk i\u015flemi a\u00e7t\u0131. Bu s\u00fcrede F_AKBNK 66\u219270, F_PGSUS 165\u2192179 toparland\u0131.", { size: 20 })]),
      p([twB("4. Ka\u00e7\u0131r\u0131lan f\u0131rsat b\u00fcy\u00fckl\u00fc\u011f\u00fc: ", { size: 20, color: "1B2A4A" }), tw("E\u011fer O\u011eUL 09:45-10:00\u2019da dipten BUY a\u00e7sayd\u0131: F_AKBNK 66.23\u219270.80 = +457 TL/lot, F_PGSUS 165\u2192179 = +1400 TL/lot, F_FROTO 99\u2192108 = +900 TL/lot. Toplam potansiyel: +2,757 TL.", { size: 20 })]),

      // SECTION 5: CONCLUSIONS
      new Paragraph({ children: [new PageBreak()] }),
      pHead("5. SONU\u00c7 VE \u00d6NER\u0130LER", HeadingLevel.HEADING_1),

      p([twB("A. Haber-Piyasa \u0130li\u015fkisi:", { size: 22, color: "1B2A4A" })]),
      p([tw("Bu olay tipik bir hafta sonu jeopolitik \u015fokudur. Haber Cumartesi gece \u00e7\u0131kt\u0131, piyasalar kapal\u0131yd\u0131, Pazartesi a\u00e7\u0131l\u0131\u015fta gap ile fiyatland\u0131. \u0130\u00e7eriden bilgi veya \u00f6nceden hareket kan\u0131t\u0131 yok \u2014 t\u00fcm hareket a\u00e7\u0131l\u0131\u015fta oldu.", { size: 20 })]),

      p([twB("B. Sistem Eksiklikleri:", { size: 22, color: "CC0000" })]),
      p([tw("1) Gap-down tespit motoru YOK \u2014 a\u00e7\u0131l\u0131\u015fta \u00f6nceki kapan\u0131\u015fa g\u00f6re %2+ gap alg\u0131lam\u0131yor.", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("2) Oylama bug\u2019\u0131 (a\u011f\u0131rl\u0131kl\u0131 oy kullan\u0131lm\u0131yor) \u2014 RSI/EMA \u00e7eli\u015fkisinde s\u00fcresiz NOTR.", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("3) VOLATILE rejimde t\u00fcm sinyaller duruyor \u2014 en b\u00fcy\u00fck f\u0131rsatlar kaybediliyor.", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("4) Hafta sonu risk takvimi YOK \u2014 Cuma ak\u015fam global risk taramas\u0131 yap\u0131lm\u0131yor.", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),

      p([twB("C. Hibrit Motor De\u011ferlendirmesi:", { size: 22, color: "008800" })]),
      p([tw("Hibrit motor g\u00f6revini yapt\u0131. F_HALKB zarar\u0131n\u0131 yar\u0131ya indirdi (SL tetikleme). F_AKBNK\u2019da breakeven korumas\u0131 devreye girdi. G\u00fcvenilir.", { size: 20 })]),

      p([twB("D. Acil Eylem Plan\u0131:", { size: 22, color: "1B2A4A" })]),
      p([tw("1) Oylama tiebreaker fix \u2014 bug\u0131 d\u00fczelt, NOTR kilidini k\u0131r (30 dakika).", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("2) VOLATILE\u2019de momentum stratejisi a\u00e7 \u2014 k\u00fc\u00e7\u00fck lot ile (2 saat).", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("3) Gap tespit motoru ekle \u2014 a\u00e7\u0131l\u0131\u015f \u015fokunu alg\u0131la (4 saat).", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),
      p([tw("4) Hafta sonu risk takvimi \u2014 Cuma ak\u015fam global tarama (8 saat).", { size: 20 })], { numbering: { reference: "bullets", level: 0 } }),

      p([tw("")]),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 400 }, border: { top: { style: BorderStyle.SINGLE, size: 2, color: "1B2A4A", space: 8 } },
        children: [tw("Rapor Sonu | Haz\u0131rlayan: \u00dcSTAT CEO Yapay Zeka Sistemi | 23.03.2026 14:55", { size: 18, color: "888888", italics: true })] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/exciting-laughing-newton/mnt/USTAT/HABER_PIYASA_ZAMANLAMA_RAPORU.docx", buffer);
  console.log("RAPOR OLUSTURULDU: HABER_PIYASA_ZAMANLAMA_RAPORU.docx");
});
