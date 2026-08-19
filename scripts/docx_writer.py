# -*- coding: utf-8 -*-
"""Escritor mínimo de .docx (OOXML), sem dependência externa.

Existe para que `conteudo_editorial.py` possa gerar o documento editorial a
partir do próprio código, em qualquer máquina, sem exigir pandoc, LibreOffice
ou python-docx. Cobre só o que aquele documento usa: título, três níveis de
cabeçalho, parágrafo, parágrafo de destaque, lista com marcador e tabela com
cabeçalho e bordas.

Um .docx é um zip com quatro partes: os tipos de conteúdo, a relação raiz, os
estilos e o documento. É o que se monta aqui.
"""

from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""


def _style(sid, name, *, size=None, bold=False, color=None, before=0, after=120,
           outline=None, based="Normal", mono=False, italic=False):
    ppr = [f'<w:spacing w:before="{before}" w:after="{after}"/>']
    if outline is not None:
        ppr.append(f'<w:outlineLvl w:val="{outline}"/>')
        ppr.append('<w:keepNext/>')
    rpr = []
    if mono:
        rpr.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>')
    if bold:
        rpr.append('<w:b/>')
    if italic:
        rpr.append('<w:i/>')
    if size:
        rpr.append(f'<w:sz w:val="{size}"/>')
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    return (
        f'<w:style w:type="paragraph" w:styleId="{sid}">'
        f'<w:name w:val="{name}"/><w:basedOn w:val="{based}"/>'
        f'<w:pPr>{"".join(ppr)}</w:pPr><w:rPr>{"".join(rpr)}</w:rPr></w:style>'
    )


_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="21"/>
</w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>
<w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:style>
{_style("Title", "Title", size=40, bold=True, after=80, outline=0, color="1F3864")}
{_style("Subtitle", "Subtitle", size=20, italic=True, after=320, color="595959")}
{_style("Heading1", "heading 1", size=30, bold=True, before=360, after=140, outline=0, color="1F3864")}
{_style("Heading2", "heading 2", size=25, bold=True, before=280, after=120, outline=1, color="2E5496")}
{_style("Heading3", "heading 3", size=22, bold=True, before=220, after=100, outline=2, color="333333")}
{_style("Fonte", "Fonte", size=18, italic=True, after=160, color="7F7F7F")}
{_style("Mono", "Mono", size=18, mono=True, after=100)}
{_style("Nota", "Nota", size=19, italic=True, after=140, color="7F5F00")}
<w:style w:type="paragraph" w:styleId="Bullet"><w:name w:val="List Bullet"/>
<w:basedOn w:val="Normal"/><w:pPr>
<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>
<w:spacing w:after="60"/><w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>
</w:styles>"""

_NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {W}>
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>
<w:lvlText w:val="&#8226;"/><w:lvlJc w:val="left"/>
<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:hint="default"/></w:rPr>
</w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""

_SECTPR = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"'
    ' w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
)


class Docx:
    """Acumula parágrafos e tabelas e grava o arquivo."""

    def __init__(self):
        self._body: list[str] = []

    # ------------------------------------------------------------- runs
    @staticmethod
    def _runs(texto: str, *, bold=False, mono=False, italic=False) -> str:
        rpr = []
        if mono:
            rpr.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>')
        if bold:
            rpr.append('<w:b/>')
        if italic:
            rpr.append('<w:i/>')
        rpr = f'<w:rPr>{"".join(rpr)}</w:rPr>' if rpr else ""
        partes = str(texto).split("\n")
        out = []
        for i, parte in enumerate(partes):
            if i:
                out.append("<w:r><w:br/></w:r>")
            out.append(
                f'<w:r>{rpr}<w:t xml:space="preserve">{escape(parte)}</w:t></w:r>'
            )
        return "".join(out)

    # -------------------------------------------------------- parágrafos
    def p(self, texto="", style="Normal", *, bold=False, mono=False,
          italic=False):
        self._body.append(
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f"{self._runs(texto, bold=bold, mono=mono, italic=italic)}</w:p>"
        )

    def title(self, t):
        self.p(t, "Title")

    def subtitle(self, t):
        self.p(t, "Subtitle")

    def h1(self, t):
        self.p(t, "Heading1")

    def h2(self, t):
        self.p(t, "Heading2")

    def h3(self, t):
        self.p(t, "Heading3")

    def fonte(self, t):
        """Linha de origem: arquivo e símbolo de onde o texto vem."""
        self.p(t, "Fonte")

    def nota(self, t):
        self.p(t, "Nota")

    def mono(self, t):
        self.p(t, "Mono")

    def bullets(self, itens):
        for i in itens:
            self.p(i, "Bullet")

    def campo(self, rotulo, valor):
        """Parágrafo 'Rótulo: valor', com o rótulo em negrito."""
        self._body.append(
            "<w:p>"
            f"{self._runs(rotulo + ': ', bold=True)}{self._runs(valor)}</w:p>"
        )

    # ------------------------------------------------------------ tabela
    def table(self, cabecalho, linhas, larguras=None):
        n = len(cabecalho)
        larguras = larguras or [round(9638 / n)] * n
        borda = (
            '<w:tblBorders>'
            + "".join(
                f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                for b in ("top", "left", "bottom", "right", "insideH", "insideV")
            )
            + "</w:tblBorders>"
        )
        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in larguras)
        out = [
            '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
            f'<w:tblW w:w="{sum(larguras)}" w:type="dxa"/>{borda}'
            '<w:tblLayout w:type="fixed"/></w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>"
        ]

        def linha(celulas, cab=False):
            tr = ['<w:tr>']
            if cab:
                tr.append('<w:trPr><w:tblHeader/></w:trPr>')
            for w, c in zip(larguras, celulas):
                sombra = ('<w:shd w:val="clear" w:color="auto" w:fill="EDF2F9"/>'
                          if cab else "")
                tr.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{sombra}'
                    '<w:vAlign w:val="top"/></w:tcPr>'
                    '<w:p><w:pPr><w:spacing w:after="40"/></w:pPr>'
                    f"{self._runs(c, bold=cab)}</w:p></w:tc>"
                )
            tr.append("</w:tr>")
            return "".join(tr)

        out.append(linha(cabecalho, cab=True))
        for l in linhas:
            out.append(linha(l))
        out.append("</w:tbl>")
        # Word exige um parágrafo depois da tabela para não colar na seguinte.
        out.append('<w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')
        self._body.append("".join(out))

    def quebra_de_pagina(self):
        self._body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    # ------------------------------------------------------------ gravar
    def save(self, caminho):
        doc = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {W}><w:body>{''.join(self._body)}{_SECTPR}</w:body></w:document>"
        )
        try:
            open(caminho, "ab").close()
        except PermissionError:
            raise PermissionError(
                f"{caminho} está aberto em outro programa (Word costuma "
                f"travar o arquivo). Feche-o e rode de novo."
            ) from None
        with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", _RELS)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
            z.writestr("word/styles.xml", _STYLES)
            z.writestr("word/numbering.xml", _NUMBERING)
            z.writestr("word/document.xml", doc)
        return caminho
