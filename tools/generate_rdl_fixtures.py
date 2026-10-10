"""Rebuild the generated RDL rule fixtures from DS-02.rdl, one small edit each.

    python tools/generate_rdl_fixtures.py                # rewrite every generated fixture
    python tools/generate_rdl_fixtures.py LAY-01-Pass    # rewrite just these
    python tools/generate_rdl_fixtures.py --check        # exit 1 if a committed one differs

Each active rule gets two fixtures in ``fabric-artifacts/``: ``<RULE-ID>``,
which must trip it, and ``<RULE-ID>-Pass``, a near-miss that must trip no rule.
Both are DS-02.rdl (a real Report Builder file) with its dataset used, plus
one edit. The output is deterministic, down to each report's ``rd:ReportID``,
so tests/test_rdl_fixture_generator.py can require the committed files to
match. A new or changed fixture then goes through
``tools/deploy_rdl_fixtures.py`` so the Fabric service accepts it and
writes its ``.platform``.

Fixtures for planned rules are defined but not written (PRM-04: the service
rejects a MultiValue + Nullable parameter). The hand-built fixtures
(ACC-03, DS-02, DS-05, DS-07, QRY-01, QRY-02, QRY-04, STR-01) are not generated.
"""

import argparse
import functools
import json
import re
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO / "fabric-artifacts"
CATALOG = REPO / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json"
BASE = ARTIFACTS / "DS-02.PaginatedReport" / "DS-02.rdl"

raw = BASE.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def ind(xml, n):
    return "\n".join((" " * n + line) if line.strip() else line for line in xml.strip("\n").split("\n"))


def textbox(name, value, top, left="0in", width="5.5in", height="0.25in", extra_run="", extra_box=""):
    return f"""<Textbox Name="{name}">
  <CanGrow>true</CanGrow>
  <KeepTogether>true</KeepTogether>
  <Paragraphs>
    <Paragraph>
      <TextRuns>
        <TextRun>
          <Value>{value}</Value>{extra_run}
          <Style />
        </TextRun>
      </TextRuns>
      <Style />
    </Paragraph>
  </Paragraphs>{extra_box}
  <Top>{top}</Top>
  <Left>{left}</Left>
  <Height>{height}</Height>
  <Width>{width}</Width>
  <Style>
    <Border>
      <Style>None</Style>
    </Border>
    <PaddingLeft>2pt</PaddingLeft>
    <PaddingRight>2pt</PaddingRight>
    <PaddingTop>2pt</PaddingTop>
    <PaddingBottom>2pt</PaddingBottom>
  </Style>
</Textbox>"""


BODY_END = "        </ReportItems>\n        <Height>2.25in</Height>"


def _require(condition, message):
    """Stop with a message when an edit's anchor is missing, rather than write a fixture without the edit."""
    if not condition:
        raise ValueError(message)


_require(raw.count(BODY_END) == 1, "DS-02.rdl no longer has one Body ReportItems anchor")


def add_body(text, xml):
    _require(text.count(BODY_END) == 1, "body anchor missing")
    return text.replace(BODY_END, ind(xml, 10) + "\n" + BODY_END)


def add_report_level(text, xml):
    """Insert a Report child just before ReportParametersLayout."""
    anchor = "  <ReportParametersLayout>"
    _require(text.count(anchor) == 1, "ReportParametersLayout anchor missing")
    return text.replace(anchor, ind(xml, 2) + "\n" + anchor)


def add_datasource(text, xml):
    anchor = "  </DataSources>"
    return text.replace(anchor, ind(xml, 4) + "\n" + anchor)


def add_dataset(text, xml):
    anchor = "  </DataSets>"
    return text.replace(anchor, ind(xml, 4) + "\n" + anchor)


def add_parameter(text, name, default=True, extra="", default_value="All", data_type="String"):
    values = default_value if isinstance(default_value, list) else [default_value]
    value_xml = "".join(f"\n      <Value>{v}</Value>" for v in values)
    default_xml = (
        f"""
  <DefaultValue>
    <Values>{value_xml}
    </Values>
  </DefaultValue>"""
        if default
        else ""
    )
    param = f"""<ReportParameter Name="{name}">
  <DataType>{data_type}</DataType>{default_xml}{extra}
  <Prompt>{name}</Prompt>
</ReportParameter>"""
    anchor = "  </ReportParameters>"
    text = text.replace(anchor, ind(param, 4) + "\n" + anchor)
    row, col = divmod(len(re.findall(r"<CellDefinition>", text)), 4)
    cell = f"""<CellDefinition>
  <ColumnIndex>{col}</ColumnIndex>
  <RowIndex>{row}</RowIndex>
  <ParameterName>{name}</ParameterName>
</CellDefinition>"""
    _require(text.count("      </CellDefinitions>") == 1, "cell anchor missing")
    return text.replace("      </CellDefinitions>", ind(cell, 8) + "\n      </CellDefinitions>")


# SampleModel-PQLAssert in fab-test [Dev], as Report Builder writes a PBIDATASET connection.
SEMANTIC_CONNECT = (
    'Data Source=pbiazure://api.powerbi.com/;Identity Provider="https://login.microsoftonline.com/organizations, '
    'https://analysis.windows.net/powerbi/api, f0b72488-7082-488a-a7e8-eada97bd842d";'
    "Initial Catalog=sobe_wowvirtualserver-c2aa40cc-d4e2-46ab-9cd6-ec9c65f8cc25;Integrated Security=ClaimsToken"
)
SEMANTIC_SOURCE = f"""<DataSource Name="SampleModel">
  <rd:SecurityType>None</rd:SecurityType>
  <ConnectionProperties>
    <DataProvider>PBIDATASET</DataProvider>
    <ConnectString>{SEMANTIC_CONNECT}</ConnectString>
  </ConnectionProperties>
  <rd:DataSourceID>6b0f3f8e-2d7c-4b55-9a51-3c1f2b8f0a11</rd:DataSourceID>
  <rd:PowerBIWorkspaceName>fab-test [Dev]</rd:PowerBIWorkspaceName>
  <rd:PowerBIDatasetName>SampleModel-PQLAssert</rd:PowerBIDatasetName>
</DataSource>"""


def dax_dataset(name, dax, fields):
    fx = "\n".join(
        f"""  <Field Name="{f}">
    <rd:TypeName>{t}</rd:TypeName>
    <DataField>{df}</DataField>
  </Field>"""
        for f, df, t in fields
    )
    return f"""<DataSet Name="{name}">
  <Query>
    <DataSourceName>SampleModel</DataSourceName>
    <CommandText>{dax}</CommandText>
  </Query>
  <Fields>
{fx}
  </Fields>
</DataSet>"""


CHARACTERS = dax_dataset(
    "Characters",
    "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], MarvelFact[AlignmentID], MarvelFact[Appearances])",
    [
        ("Name", "MarvelFact[Name]", "System.String"),
        ("AlignmentID", "MarvelFact[AlignmentID]", "System.Int64"),
        ("Appearances", "MarvelFact[Appearances]", "System.Int64"),
    ],
)
ALIGNMENTS = dax_dataset(
    "Alignments",
    "EVALUATE SUMMARIZECOLUMNS(AlignmentDim[AlignmentID], AlignmentDim[Alignment])",
    [
        ("AlignmentID", "AlignmentDim[AlignmentID]", "System.Int64"),
        ("Alignment", "AlignmentDim[Alignment]", "System.String"),
    ],
)


def with_semantic(text, *datasets):
    text = add_datasource(text, SEMANTIC_SOURCE)
    for ds in datasets:
        text = add_dataset(text, ds)
    return text


def cell(name, value, extra_box=""):
    tb = textbox(name, value, "0in", extra_box=extra_box)
    tb = re.sub(r"\n  <Top>.*?</Width>", "", tb, flags=re.S)  # cells carry no position
    return f"""<TablixCell>
  <CellContents>
{ind(tb, 4)}
  </CellContents>
</TablixCell>"""


def tablix(
    name,
    dataset,
    header,
    detail,
    tooltip="Characters and their appearances",
    group='<Group Name="Details" />',
    top="1in",
    detail_cells_xml=None,
    extra="",
):
    cols = len(header)
    columns = "\n".join("    <TablixColumn>\n      <Width>1.5in</Width>\n    </TablixColumn>" for _ in range(cols))
    hdr = "\n".join(ind(cell(f"{name}_H{i}", v), 8) for i, v in enumerate(header))
    det = detail_cells_xml or "\n".join(ind(cell(f"{name}_D{i}", v), 8) for i, v in enumerate(detail))
    members = "\n".join("    <TablixMember />" for _ in range(cols))
    tip = f"\n<ToolTip>{tooltip}</ToolTip>" if tooltip else ""
    return f"""<Tablix Name="{name}">
  <TablixBody>
    <TablixColumns>
{columns}
    </TablixColumns>
    <TablixRows>
      <TablixRow>
        <Height>0.25in</Height>
        <TablixCells>
{hdr}
        </TablixCells>
      </TablixRow>
      <TablixRow>
        <Height>0.25in</Height>
        <TablixCells>
{det}
        </TablixCells>
      </TablixRow>
    </TablixRows>
  </TablixBody>
  <TablixColumnHierarchy>
    <TablixMembers>
{members}
    </TablixMembers>
  </TablixColumnHierarchy>
  <TablixRowHierarchy>
    <TablixMembers>
      <TablixMember>
        <KeepWithGroup>After</KeepWithGroup>
      </TablixMember>
      <TablixMember>
{ind(group, 8)}
      </TablixMember>
    </TablixMembers>
  </TablixRowHierarchy>
  <DataSetName>{dataset}</DataSetName>{extra}
  <Top>{top}</Top>
  <Height>0.5in</Height>
  <Width>{1.5 * cols}in</Width>{tip}
  <Style>
    <Border>
      <Style>None</Style>
    </Border>
  </Style>
</Tablix>"""


def axis(name):
    return f"""<ChartAxis Name="{name}">
  <Style />
  <ChartAxisTitle>
    <Caption />
    <Style />
  </ChartAxisTitle>
  <ChartMajorGridLines>
    <Style />
  </ChartMajorGridLines>
  <ChartMinorGridLines>
    <Style />
  </ChartMinorGridLines>
  <CrossAt>NaN</CrossAt>
  <Minimum>NaN</Minimum>
  <Maximum>NaN</Maximum>
  <ChartAxisScaleBreak>
    <Style />
  </ChartAxisScaleBreak>
</ChartAxis>"""


def chart(name, tooltip):
    tip = f"\n<ToolTip>{tooltip}</ToolTip>" if tooltip else ""
    return f"""<Chart Name="{name}">
  <ChartCategoryHierarchy>
    <ChartMembers>
      <ChartMember>
        <Group Name="{name}_CategoryGroup">
          <GroupExpressions>
            <GroupExpression>=Fields!AlignmentID.Value</GroupExpression>
          </GroupExpressions>
        </Group>
        <Label>=Fields!AlignmentID.Value</Label>
      </ChartMember>
    </ChartMembers>
  </ChartCategoryHierarchy>
  <ChartSeriesHierarchy>
    <ChartMembers>
      <ChartMember>
        <Label>Appearances</Label>
      </ChartMember>
    </ChartMembers>
  </ChartSeriesHierarchy>
  <ChartData>
    <ChartSeriesCollection>
      <ChartSeries Name="Appearances">
        <ChartDataPoints>
          <ChartDataPoint>
            <ChartDataPointValues>
              <Y>=Sum(Fields!Appearances.Value)</Y>
            </ChartDataPointValues>
            <ChartDataLabel>
              <Style />
            </ChartDataLabel>
            <Style />
            <ChartMarker>
              <Style />
            </ChartMarker>
            <DataElementOutput>Output</DataElementOutput>
          </ChartDataPoint>
        </ChartDataPoints>
        <Type>Bar</Type>
        <Style />
        <ChartEmptyPoints>
          <Style />
          <ChartMarker>
            <Style />
          </ChartMarker>
          <ChartDataLabel>
            <Style />
          </ChartDataLabel>
        </ChartEmptyPoints>
        <ValueAxisName>Primary</ValueAxisName>
        <CategoryAxisName>Primary</CategoryAxisName>
        <ChartSmartLabel>
          <CalloutLineColor>Black</CalloutLineColor>
          <MinMovingDistance>0pt</MinMovingDistance>
        </ChartSmartLabel>
      </ChartSeries>
    </ChartSeriesCollection>
  </ChartData>
  <ChartAreas>
    <ChartArea Name="Default">
      <ChartCategoryAxes>
{ind(axis("Primary"), 8)}
      </ChartCategoryAxes>
      <ChartValueAxes>
{ind(axis("Primary"), 8)}
      </ChartValueAxes>
      <Style />
    </ChartArea>
  </ChartAreas>
  <Palette>Default</Palette>
  <ChartBorderSkin>
    <Style>
      <BackgroundColor>Gray</BackgroundColor>
      <BackgroundGradientType>None</BackgroundGradientType>
      <Color>White</Color>
    </Style>
  </ChartBorderSkin>
  <ChartNoDataMessage Name="NoDataMessage">
    <Caption>No Data Available</Caption>
    <Style />
  </ChartNoDataMessage>
  <DataSetName>Characters</DataSetName>
  <Top>1in</Top>
  <Height>1.2in</Height>
  <Width>4in</Width>
  <ZIndex>2</ZIndex>{tip}
  <Style>
    <Border>
      <Style>None</Style>
    </Border>
  </Style>
</Chart>"""


SQL_SOURCE = """<DataSource Name="EscapeRoom">
  <rd:SecurityType>DataBase</rd:SecurityType>
  <ConnectionProperties>
    <DataProvider>SQLAZURE</DataProvider>
    <ConnectString>Data Source=azure-sql-db-jk.database.windows.net;Initial Catalog=escape-room</ConnectString>
    <Prompt>Specify a user name and password for data source EscapeRoom:</Prompt>
  </ConnectionProperties>
  <rd:DataSourceID>55ef01f2-bf06-4fbb-9532-dd87cc4121e7</rd:DataSourceID>
</DataSource>"""

PIE_FIELDS = """  <Fields>
    <Field Name="PieID">
      <rd:TypeName>System.Int32</rd:TypeName>
      <DataField>PieID</DataField>
    </Field>
    <Field Name="PieName">
      <rd:TypeName>System.String</rd:TypeName>
      <DataField>PieName</DataField>
    </Field>
  </Fields>"""

# 1x1 transparent PNG
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def image(name, source, value, tooltip=None, top="1in"):
    tip = f"\n<ToolTip>{tooltip}</ToolTip>" if tooltip else ""
    return f"""<Image Name="{name}">
  <Source>{source}</Source>
  <Value>{value}</Value>
  <Sizing>FitProportional</Sizing>
  <Top>{top}</Top>
  <Left>5.5in</Left>
  <Height>0.5in</Height>
  <Width>0.5in</Width>
  <ZIndex>2</ZIndex>{tip}
  <Style>
    <Border>
      <Style>None</Style>
    </Border>
  </Style>
</Image>"""


def subreport(name, top):
    return f"""<Subreport Name="{name}">
  <ReportName>LAY-02</ReportName>
  <Top>{top}</Top>
  <Height>0.25in</Height>
  <Width>5.5in</Width>
  <Style>
    <Border>
      <Style>None</Style>
    </Border>
  </Style>
</Subreport>"""


def subreport_cell():
    return """<TablixCell>
  <CellContents>
    <Subreport Name="AlignmentDetail">
      <ReportName>LAY-02</ReportName>
      <Style>
        <Border>
          <Style>None</Style>
        </Border>
      </Style>
    </Subreport>
  </CellContents>
</TablixCell>"""


def html_link():
    return textbox(
        "DocsLink",
        '="&lt;a href=""https://learn.microsoft.com/power-bi/paginated-reports/""&gt;Paginated report docs&lt;/a&gt;"',
        "1in",
        extra_run="\n          <MarkupType>HTML</MarkupType>",
    )


def sql_dataset(name, command, command_type=""):
    ct = f"\n    <CommandType>{command_type}</CommandType>" if command_type else ""
    return f"""<DataSet Name="{name}">
  <Query>
    <DataSourceName>EscapeRoom</DataSourceName>{ct}
    <CommandText>{command}</CommandText>
  </Query>
{PIE_FIELDS}
</DataSet>"""


def long_sql(conditions=51):
    """conditions + 8 lines of SQL."""
    lines = ["SELECT", "    p.PieID,", "    p.PieName", "FROM PieData AS p", "WHERE p.PieID &gt; 0", "  AND ("]
    lines += [f"       {'OR ' if i > 1 else '   '}p.PieName = 'Pie {i}'" for i in range(1, conditions + 1)]
    lines += ["  )", "ORDER BY p.PieName"]
    return "\n".join(lines)


def alignment_group(page_break=True):
    brk = (
        """
  <PageBreak>
    <BreakLocation>Between</BreakLocation>
  </PageBreak>"""
        if page_break
        else ""
    )
    return f"""<Group Name="Alignment">
  <GroupExpressions>
    <GroupExpression>=Fields!AlignmentID.Value</GroupExpression>
  </GroupExpressions>{brk}
</Group>"""


FIXTURES = {
    "PRM-01": lambda t: t.replace(
        """      <DefaultValue>
        <Values>
          <Value>88b5780c-ab04-432a-8d14-e8c8a17c2e2e</Value>
        </Values>
      </DefaultValue>
""",
        "",
    ),
    "PRM-03": lambda t: add_body(
        add_parameter(add_parameter(t, "Year"), "Month"),
        textbox("ShownParameters", '=Parameters!Year.Value &amp; " " &amp; Parameters!Month.Value', "1in"),
    ),
    "PRM-04": lambda t: add_body(
        add_parameter(t, "Alignment", extra="\n  <Nullable>true</Nullable>\n  <MultiValue>true</MultiValue>"),
        textbox("ShownParameters", '=Join(Parameters!Alignment.Value, ", ")', "1in"),
    ),
    "PRM-05": lambda t: add_parameter(t, "Region"),
    "LAY-01": lambda t: t.replace("      <Width>6in</Width>\n      <Page>", "      <Width>7in</Width>\n      <Page>"),
    "LAY-02": lambda t: t.replace(
        "<Value>=Globals!ExecutionTime</Value>",
        '<Value>="Page " &amp; Globals!PageNumber &amp; " of " &amp; Globals!TotalPages</Value>',
    ),
    "LAY-04": lambda t: add_body(
        with_semantic(t, CHARACTERS),
        tablix(
            "CharacterTable",
            "Characters",
            ["Name", "Appearances"],
            ["=Fields!Name.Value", "=Fields!Appearances.Value"],
            group=alignment_group(),
        ).replace(
            '<Textbox Name="CharacterTable_H0">',
            '<Textbox Name="CharacterTable_H0">\n                  <UserSort>\n'
            "                    <SortExpression>=Fields!Name.Value</SortExpression>\n                  </UserSort>",
            1,
        ),
    ),
    "LAY-05": lambda t: add_body(
        with_semantic(t, CHARACTERS),
        tablix(
            "CharacterTable",
            "Characters",
            ["Name", "Appearances"],
            ["=Fields!Name.Value", "=Fields!Appearances.Value"],
            group=alignment_group(page_break=False),
        ),
    ),
    "LAY-06": lambda t: add_report_level(
        add_body(t, image("Logo", "Embedded", "logo", tooltip="fab-test logo")),
        f"""<EmbeddedImages>
  <EmbeddedImage Name="logo">
    <MIMEType>image/png</MIMEType>
    <ImageData>{PNG}</ImageData>
  </EmbeddedImage>
</EmbeddedImages>""",
    ),
    "LAY-03": lambda t: add_body(
        with_semantic(t, ALIGNMENTS),
        tablix(
            "AlignmentTable",
            "Alignments",
            ["Alignment", "Detail"],
            None,
            group=alignment_group(),
            detail_cells_xml=ind(cell("AlignmentTable_D0", "=Fields!Alignment.Value"), 8)
            + "\n"
            + ind(subreport_cell(), 8),
        ),
    ),
    "SUB-02": lambda t: add_body(
        t, "\n".join(subreport(f"Subreport{i}", f"{1 + i * 0.25:.2f}in") for i in range(50))
    ).replace(BODY_END, BODY_END.replace("2.25in", "14in")),
    "ACC-01": lambda t: add_body(t, image("Logo", "External", "https://learn.microsoft.com/favicon.ico")),
    "ACC-02": lambda t: add_body(with_semantic(t, CHARACTERS), chart("Chart1", "Chart1")),
    "ACC-08": lambda t: add_body(t, html_link()),
    "QRY-03": lambda t: add_body(t, textbox("CharacterCount", '=Count(Fields!name.Value, "RawSourceExample")', "1in")),
    "QRY-05": lambda t: add_body(
        with_semantic(t, CHARACTERS),
        tablix(
            "CharacterTable",
            "Characters",
            ["Name", "Appearances", "Appearances x2"],
            ["=Fields!Name.Value", "=CInt(Fields!Appearances.Value)", "=CInt(Fields!Appearances.Value) * 2"],
            group=alignment_group(),
        ),
    ),
    "QRY-06": lambda t: add_body(
        with_semantic(t, CHARACTERS, ALIGNMENTS),
        tablix(
            "CharacterTable",
            "Characters",
            ["Name", "Alignment"],
            [
                "=Fields!Name.Value",
                '=Lookup(Fields!AlignmentID.Value, Fields!AlignmentID.Value, Fields!Alignment.Value, "Alignments")',
            ],
            group=alignment_group(),
        ),
    ),
    "QRY-07": lambda t: add_body(
        add_dataset(add_datasource(t, SQL_SOURCE), sql_dataset("Pies", long_sql())),
        textbox("FirstPie", '=First(Fields!PieName.Value, "Pies")', "1in"),
    ),
    "DS-01": lambda t: add_body(
        add_dataset(
            add_datasource(
                t,
                SQL_SOURCE.replace(
                    "Initial Catalog=escape-room</ConnectString>",
                    # A fake password: DS-01 must see one, and it never echoes it.
                    "Initial Catalog=escape-room;User ID=report_reader;"
                    "Password=NotARealPassword-fixture</ConnectString>",
                )
                .replace("<rd:SecurityType>DataBase</rd:SecurityType>", "<rd:SecurityType>None</rd:SecurityType>")
                .replace("\n    <Prompt>Specify a user name and password for data source EscapeRoom:</Prompt>", ""),
            ),
            sql_dataset("Pies", "dbo.GetPies", "StoredProcedure"),
        ),
        textbox("FirstPie", '=First(Fields!PieName.Value, "Pies")', "1in"),
    ),
}
FIXTURES["SUB-01"] = FIXTURES["LAY-03"]

# --------------------------------------------------------------------------- #
# Tier B
# --------------------------------------------------------------------------- #
ALIGNMENT_LIST = dax_dataset(
    "AlignmentList",
    'EVALUATE DATATABLE("Alignment", STRING, {{"Good"}, {"Bad"}, {"Neutral"}})',
    [("Alignment", "[Alignment]", "System.String")],
)


def alignment_parameter(text, dataset_name):
    valid = f"""
  <ValidValues>
    <DataSetReference>
      <DataSetName>{dataset_name}</DataSetName>
      <ValueField>Alignment</ValueField>
      <LabelField>Alignment</LabelField>
    </DataSetReference>
  </ValidValues>"""
    text = add_parameter(text, "Alignment", extra=valid, default_value="Good")
    return add_body(text, textbox("ShownParameters", "=Parameters!Alignment.Value", "1in"))


FIXTURES["DS-03"] = lambda t: alignment_parameter(with_semantic(t, ALIGNMENT_LIST), "AlignmentList")


CHARACTERS_TWO_FIELDS = dax_dataset(
    "Characters",
    "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], MarvelFact[AlignmentID], MarvelFact[Appearances])",
    [("Name", "MarvelFact[Name]", "System.String"), ("Appearances", "MarvelFact[Appearances]", "System.Int64")],
)
FIXTURES["DS-06"] = lambda t: add_body(
    with_semantic(t, CHARACTERS_TWO_FIELDS), textbox("FirstName", '=First(Fields!Name.Value, "Characters")', "1in")
)


def alignment_characters(name, alignment_id):
    return dax_dataset(
        name,
        "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], MarvelFact[Appearances], "
        f"KEEPFILTERS(TREATAS({{{alignment_id}}}, MarvelFact[AlignmentID])))",
        [("Name", "MarvelFact[Name]", "System.String"), ("Appearances", "MarvelFact[Appearances]", "System.Int64")],
    )


FIXTURES["DS-04"] = lambda t: add_body(
    with_semantic(t, alignment_characters("GoodCharacters", 1), alignment_characters("BadCharacters", 2)),
    tablix(
        "GoodTable",
        "GoodCharacters",
        ["Hero", "Appearances"],
        ["=Fields!Name.Value", "=Fields!Appearances.Value"],
        tooltip="Heroes and their appearances",
    )
    + chr(10)
    + tablix(
        "BadTable",
        "BadCharacters",
        ["Villain", "Appearances"],
        ["=Fields!Name.Value", "=Fields!Appearances.Value"],
        tooltip="Villains and their appearances",
        group='<Group Name="Details1" />',
        top="1.6in",
    ),
)


ALIGNMENT_IDS = dax_dataset(
    "AlignmentIDs",
    "EVALUATE SUMMARIZECOLUMNS(AlignmentDim[AlignmentID])",
    [("AlignmentID", "AlignmentDim[AlignmentID]", "System.Int64")],
)


def alignment_id_parameter(text):
    valid = """
  <ValidValues>
    <DataSetReference>
      <DataSetName>AlignmentIDs</DataSetName>
      <ValueField>AlignmentID</ValueField>
    </DataSetReference>
  </ValidValues>"""
    text = add_parameter(text, "AlignmentID", extra=valid, default_value="1")
    return add_body(text, textbox("ShownParameters", "=Parameters!AlignmentID.Value", "1in"))


FIXTURES["PRM-02"] = lambda t: alignment_id_parameter(with_semantic(t, ALIGNMENT_IDS))


CHANGES = dax_dataset(
    "Changes",
    "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], MarvelFact[Test Change])",
    [("Name", "MarvelFact[Name]", "System.String"), ("Test_Change", "MarvelFact[Test Change]", "System.Int64")],
)
FIXTURES["STR-03"] = lambda t: add_body(
    with_semantic(t, CHANGES), textbox("FirstChange", '=First(Fields!Test_Change.Value, "Changes")', "1in")
)


def subtitle():
    box = textbox("Subtitle", "Characters by first appearance", "0.75in")
    run_style = "<Style>\n            <Color>#AAAAAA</Color>\n          </Style>"
    return box.replace("<Style />", run_style, 1)


FIXTURES["ACC-06"] = lambda t: add_body(t, subtitle())

# --------------------------------------------------------------------------- #
# Near-miss fixtures: <RULE-ID>-Pass must not trip its rule (or any other).
# The remediated form, or a threshold just short of firing.
# --------------------------------------------------------------------------- #


def styled(box, style_inner):
    """Give a textbox's (first) text run a style."""
    return box.replace("<Style />", f"<Style>\n            {style_inner}\n          </Style>", 1)


def with_tooltip(box, tip):
    return box.replace("\n  <Top>", f"\n  <ToolTip>{tip}</ToolTip>\n  <Top>", 1)


def first_textbox(name, field, dataset_name, top="1in"):
    return textbox(name, f'=First(Fields!{field}.Value, "{dataset_name}")', top)


ALIGNMENT_NAMES = dax_dataset(
    "AlignmentNames",
    "EVALUATE SUMMARIZECOLUMNS(AlignmentDim[Alignment])",
    [("Alignment", "AlignmentDim[Alignment]", "System.String")],
)
NAMES = dax_dataset(
    "Names", 'EVALUATE SELECTCOLUMNS(MarvelFact, "Name", MarvelFact[Name])', [("Name", "[Name]", "System.String")]
)
TOTALS = dax_dataset(
    "Totals",
    'EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], "Total Appearances", SUM(MarvelFact[Appearances]))',
    [("Name", "MarvelFact[Name]", "System.String"), ("TotalAppearances", "[Total Appearances]", "System.Int64")],
)
DOUBLED = dax_dataset(
    "Doubled",
    'EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], "Doubled Appearances", SUM(MarvelFact[Appearances]) * 2)',
    [("Name", "MarvelFact[Name]", "System.String"), ("DoubledAppearances", "[Doubled Appearances]", "System.Int64")],
)
JOINED = dax_dataset(
    "Joined",
    "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], AlignmentDim[Alignment])",
    [("Name", "MarvelFact[Name]", "System.String"), ("Alignment", "AlignmentDim[Alignment]", "System.String")],
)
CHANGES_RENAMED = CHANGES.replace('Name="Test_Change"', 'Name="TestChange"')
FILTERED = dax_dataset(
    "Filtered",
    "EVALUATE SUMMARIZECOLUMNS(MarvelFact[Name], KEEPFILTERS(TREATAS({@AlignmentID}, MarvelFact[AlignmentID])))",
    [("Name", "MarvelFact[Name]", "System.String")],
).replace(
    "    <DataSourceName>SampleModel</DataSourceName>",
    '    <DataSourceName>SampleModel</DataSourceName>\n    <QueryParameters>\n      <QueryParameter Name="AlignmentID">'
    "\n        <Value>=Parameters!AlignmentID.Value</Value>\n      </QueryParameter>\n    </QueryParameters>",
    1,
)


def dataset_list(kind, dataset_name):
    return f"""
  <{kind}>
    <DataSetReference>
      <DataSetName>{dataset_name}</DataSetName>
      <ValueField>Alignment</ValueField>
    </DataSetReference>
  </{kind}>"""


def shown(text, expression, top="1.5in"):
    return add_body(text, textbox("ShownParameters", expression, top))


def characters_table(t, **kw):
    return add_body(
        with_semantic(t, CHARACTERS),
        tablix(
            "CharacterTable",
            "Characters",
            ["Name", "Appearances"],
            ["=Fields!Name.Value", "=Fields!Appearances.Value"],
            **kw,
        ),
    )


SQL_PROC = lambda t, source=SQL_SOURCE: add_body(  # noqa: E731
    add_dataset(add_datasource(t, source), sql_dataset("Pies", "dbo.GetPies", "StoredProcedure")),
    first_textbox("FirstPie", "PieName", "Pies"),
)

SORT_BY_TOTAL = (
    alignment_group()
    + """
<SortExpressions>
  <SortExpression>
    <Value>=Sum(Fields!Appearances.Value)</Value>
    <Direction>Descending</Direction>
  </SortExpression>
</SortExpressions>"""
)

PASS = {
    "STR-01": lambda t: t,
    "STR-03": lambda t: add_body(
        with_semantic(t, CHANGES_RENAMED), first_textbox("FirstChange", "TestChange", "Changes")
    ),
    "DS-01": lambda t: SQL_PROC(
        t,
        SQL_SOURCE.replace(
            "Initial Catalog=escape-room</ConnectString>",
            "Initial Catalog=escape-room;User ID=report_reader</ConnectString>",
        ),
    ),
    "DS-02": lambda t: shown(
        add_parameter(
            with_semantic(t, ALIGNMENT_NAMES),
            "Alignment",
            default=False,
            extra=dataset_list("DefaultValue", "AlignmentNames"),
        ),
        "=Parameters!Alignment.Value",
    ),
    "DS-03": lambda t: shown(
        add_parameter(
            with_semantic(t, ALIGNMENT_NAMES),
            "Alignment",
            default=False,
            extra=dataset_list("ValidValues", "AlignmentNames") + dataset_list("DefaultValue", "AlignmentNames"),
        ),
        "=Parameters!Alignment.Value",
    ),
    "DS-04": lambda t: add_body(
        with_semantic(t, CHARACTERS, ALIGNMENTS),
        tablix(
            "CharacterTable", "Characters", ["Name", "Appearances"], ["=Fields!Name.Value", "=Fields!Appearances.Value"]
        )
        + chr(10)
        + tablix(
            "AlignmentTable",
            "Alignments",
            ["ID", "Alignment"],
            ["=Fields!AlignmentID.Value", "=Fields!Alignment.Value"],
            tooltip="Alignments",
            group='<Group Name="Details1" />',
            top="1.6in",
        ),
    ),
    "DS-05": lambda t: add_body(with_semantic(t, NAMES), first_textbox("FirstName", "Name", "Names")),
    "DS-06": lambda t: add_body(with_semantic(t, TOTALS), first_textbox("FirstTotal", "TotalAppearances", "Totals")),
    "DS-07": SQL_PROC,
    "QRY-01": lambda t: shown(
        add_body(
            add_parameter(with_semantic(t, FILTERED), "AlignmentID", default_value="1", data_type="Integer"),
            first_textbox("FirstName", "Name", "Filtered"),
        ),
        "=Parameters!AlignmentID.Value",
    ),
    "QRY-02": lambda t: add_body(
        with_semantic(t, DOUBLED), first_textbox("FirstDoubled", "DoubledAppearances", "Doubled")
    ),
    "QRY-03": lambda t: characters_table(t, group=alignment_group()).replace(
        "<Value>=Fields!Appearances.Value</Value>", '<Value>=Sum(Fields!Appearances.Value, "Alignment")</Value>', 1
    ),
    "QRY-04": lambda t: characters_table(t, group=SORT_BY_TOTAL),
    "QRY-05": lambda t: characters_table(t).replace(
        "<Value>=Fields!Appearances.Value</Value>", "<Value>=CInt(Fields!Appearances.Value)</Value>", 1
    ),
    "QRY-06": lambda t: add_body(
        with_semantic(t, JOINED),
        tablix("CharacterTable", "Joined", ["Name", "Alignment"], ["=Fields!Name.Value", "=Fields!Alignment.Value"]),
    ),
    "QRY-07": lambda t: add_body(
        add_dataset(add_datasource(t, SQL_SOURCE), sql_dataset("Pies", long_sql(42))),
        first_textbox("FirstPie", "PieName", "Pies"),
    ),
    "PRM-01": lambda t: shown(
        add_parameter(t, "Region", default_value=["East", "West"], extra="\n  <MultiValue>true</MultiValue>"),
        '=Join(Parameters!Region.Value, ", ")',
    ),
    "PRM-02": lambda t: shown(
        add_parameter(
            with_semantic(t, ALIGNMENT_IDS),
            "AlignmentID",
            default_value="1",
            data_type="Integer",
            extra=dataset_list("ValidValues", "AlignmentIDs").replace(
                "<ValueField>Alignment</ValueField>", "<ValueField>AlignmentID</ValueField>"
            ),
        ),
        "=Parameters!AlignmentID.Value",
    ),
    "PRM-03": lambda t: shown(
        add_parameter(
            add_parameter(add_parameter(add_parameter(t, "Year", default_value="2026"), "Region"), "Category"), "Status"
        ),
        '=Parameters!Year.Value &amp; " " &amp; Parameters!Region.Value &amp; " " &amp; Parameters!Category.Value'
        ' &amp; " " &amp; Parameters!Status.Value',
    ),
    "PRM-04": lambda t: shown(
        add_parameter(t, "Alignment", extra="\n  <AllowBlank>true</AllowBlank>\n  <MultiValue>true</MultiValue>"),
        '=Join(Parameters!Alignment.Value, ", ")',
    ),
    "PRM-05": lambda t: shown(add_parameter(t, "Region"), "=Parameters!Region.Label"),
    "LAY-01": lambda t: t.replace("      <Width>6in</Width>\n      <Page>", "      <Width>6.5in</Width>\n      <Page>"),
    "LAY-02": lambda t: t.replace(
        "<Value>=Globals!ExecutionTime</Value>", '<Value>="Page " &amp; Globals!PageNumber</Value>'
    ),
    "LAY-03": lambda t: add_body(t, subreport("Summary", "1in")),
    "LAY-04": characters_table,
    "LAY-05": lambda t: characters_table(t, group=alignment_group()),
    "LAY-06": lambda t: add_body(
        t, image("Logo", "External", "https://learn.microsoft.com/favicon.ico", tooltip="Microsoft Learn logo")
    ),
    "SUB-02": lambda t: add_body(
        t, "\n".join(subreport(f"Subreport{i}", f"{1 + i * 0.25:.2f}in") for i in range(49))
    ).replace(BODY_END, BODY_END.replace("2.25in", "14in")),
    "ACC-01": lambda t: add_body(
        with_semantic(t, CHARACTERS),
        chart("AppearancesByAlignment", "Total appearances by alignment")
        + chr(10)
        + image("Logo", "External", "https://learn.microsoft.com/favicon.ico", tooltip="Microsoft Learn logo"),
    ),
    "ACC-02": lambda t: add_body(with_semantic(t, CHARACTERS), chart("Chart1", "Total appearances by alignment")),
    "ACC-03": characters_table,
    "ACC-06": lambda t: add_body(
        t,
        styled(textbox("Subtitle", "Characters by first appearance", "0.75in"), "<Color>#666666</Color>")
        + chr(10)
        + styled(
            textbox("Heading", "Marvel characters", "1.25in", height="0.4in"),
            "<Color>#949494</Color>\n            <FontSize>18pt</FontSize>",
        ),
    ),
    "ACC-08": lambda t: add_body(t, with_tooltip(html_link(), "Paginated report documentation on Microsoft Learn")),
}
PASS["SUB-01"] = PASS["LAY-03"]


# DS-02.rdl with its dataset used, so it trips no rule: every fixture's base.
clean = add_body(raw, textbox("FirstCharacter", '=First(Fields!name.Value, "RawSourceExample")', "0.5in"))


def active_rule_ids() -> set[str]:
    rules = json.loads(CATALOG.read_text(encoding="utf-8"))["rules"]
    return {r["id"] for r in rules if r.get("status", "active") == "active"}


def _render(name: str, text: str) -> bytes:
    report_id = uuid.uuid5(uuid.NAMESPACE_URL, "fab-test-rdl-fixture/" + name)
    text = re.sub(r"<rd:ReportID>[^<]+</rd:ReportID>", f"<rd:ReportID>{report_id}</rd:ReportID>", text)
    return b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")


@functools.cache
def fixtures() -> dict[str, bytes]:
    """Every generated fixture for an active rule, by name, as file bytes."""
    active = active_rule_ids()
    built = {rule_id: _render(rule_id, make(clean)) for rule_id, make in FIXTURES.items() if rule_id in active}
    built.update(
        {
            f"{rule_id}-Pass": _render(f"{rule_id}-Pass", make(clean))
            for rule_id, make in PASS.items()
            if rule_id in active
        }
    )
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="fixtures to write (default: all)")
    parser.add_argument("--check", action="store_true", help="exit 1 if a committed fixture differs")
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACTS)
    args = parser.parse_args(argv)
    built = fixtures()
    unknown = sorted(set(args.names) - set(built))
    if unknown:
        print(f"unknown fixture(s): {', '.join(unknown)}")
        return 2
    drifted = []
    for name in args.names or sorted(built):
        path = args.artifact_dir / f"{name}.PaginatedReport" / f"{name}.rdl"
        if args.check:
            if not path.exists() or path.read_bytes() != built[name]:
                drifted.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(built[name])
    if drifted:
        print(f"out of date: {', '.join(drifted)} -- run python tools/generate_rdl_fixtures.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
