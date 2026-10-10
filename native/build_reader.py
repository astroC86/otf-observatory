#!/usr/bin/env python3
"""Generate complete, typed OTF2 callbacks from installed public headers; no downloads."""

import os, re, shutil, subprocess, pathlib, json

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "native/src"
BUILD = ROOT / "native/build"  # generated files; safe to delete


def prefix():
    if os.environ.get("OTF2_PREFIX"):
        return pathlib.Path(os.environ["OTF2_PREFIX"]).expanduser()
    compat = ROOT / ".cache/otf2-compat/install"
    if (compat / "viewer-capabilities.json").exists() and (
        compat / "include/otf2/otf2.h"
    ).exists():
        return compat
    binary = shutil.which("otf2-print")
    if binary:
        p = pathlib.Path(binary).resolve().parent.parent
        if (p / "include/otf2/otf2.h").exists():
            return p
    for p in [pathlib.Path("/usr"), pathlib.Path("/usr/local")]:
        if (p / "include/otf2/otf2.h").exists():
            return p
    raise RuntimeError(
        "OTF2 headers/library not found. Set OTF2_PREFIX to an installed OTF2 prefix."
    )


def build():
    pre = prefix()
    inc = pre / "include/otf2"
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "otf2_reader"
    generated = BUILD / "callbacks.inc"
    callbacks = []
    registrations = []
    schema = {}
    for category in ["GlobalDef", "GlobalEvt", "Marker"]:
        source = (inc / f"OTF2_{category}ReaderCallbacks.h").read_text()
        entries = re.findall(
            r"\(\s*\*\s*OTF2_" + category + r"ReaderCallback_(\w+)\s*\)\s*\((.*?)\);",
            source,
            re.S,
        )
        registers = []
        for name, params in entries:
            args = []
            for p in params.split(","):
                t, n = re.match(r"(.*?)\s*(\w+)$", p.strip()).groups()
                args.append((t.strip(), n))
            body = []
            field_types = {}
            if category == "GlobalEvt":
                body.append(
                    'printf("{\\"record\\":\\"event\\",\\"kind\\":\\"'
                    + name
                    + '\\",\\"location\\":%" PRIu64 ",\\"time\\":%" PRIu64 ",\\"data\\":{",locationID,time);'
                )
            else:
                body.append(
                    'fputs("{\\"record\\":\\"'
                    + ("definition" if category == "GlobalDef" else "marker")
                    + '\\",\\"kind\\":\\"'
                    + name
                    + '\\",\\"data\\":{",stdout);'
                )
            fields = [
                (t, n)
                for t, n in args
                if n not in ("userData", "locationID", "time", "attributeList")
            ]
            for i, (t, n) in enumerate(fields):
                field_types[n] = t
                body.append(
                    'fputs("' + ("," if i else "") + '\\"' + n + '\\":",stdout);'
                )
                if t == "const char*":
                    body.append(f"json_string({n});")
                elif "*" in t:
                    counts = {
                        "members": "numberOfMembers",
                        "metricMembers": "numberOfMetrics",
                        "metricValues": "numberOfMetrics",
                        "typeIDs": "numberOfMetrics",
                        "cartDimensions": "numberOfDimensions",
                        "coordinates": "numberOfDimensions",
                        "programArguments": "numberOfArguments",
                        "properties": "numberOfProperties",
                        "types": "numberOfProperties",
                        "values": "numberOfProperties",
                    }
                    count = counts[n]
                    body.append(
                        f"putchar('['); for (uint32_t i=0;i<{count};i++) {{ if(i)putchar(',');"
                    )
                    if "MetricValue" in t:
                        body.append(
                            f'if(typeIDs[i]==OTF2_TYPE_DOUBLE) json_double({n}[i].floating_point); else if(typeIDs[i]==OTF2_TYPE_INT64) printf("%" PRId64,{n}[i].signed_int); else printf("%" PRIu64,{n}[i].unsigned_int);'
                        )
                    elif "AttributeValue" in t:
                        body.append(f"json_value(types[i],{n}[i]);")
                    else:
                        body.append(f'printf("%" PRIu64,(uint64_t){n}[i]);')
                    body.append("} putchar(']');")
                elif "AttributeValue" in t:
                    body.append(f"json_value(type,{n});")
                elif t.startswith("int"):
                    body.append(f'printf("%" PRId64,(int64_t){n});')
                elif t in ("double", "float"):
                    body.append(f"json_double({n});")
                else:
                    body.append(f'printf("%" PRIu64,(uint64_t){n});')
            body.append("putchar('}');")
            if category == "GlobalEvt":
                body.append("json_attributes(attributeList);")
            body.append('fputs("}\\n",stdout);')
            if category == "GlobalDef" and name == "Location":
                body.append("add_location(self);")
            body.append("return OTF2_CALLBACK_SUCCESS;")
            callbacks.append(
                f"static OTF2_CallbackCode cb_{category}_{name}({params}) {{\n"
                + "\n".join(body)
                + "\n}"
            )
            registers.append(
                f"CHECK(OTF2_{category}ReaderCallbacks_Set{name}Callback(c,cb_{category}_{name}));"
            )
            schema[f"{category}:{name}"] = field_types
        registrations.append(
            f"static void register_{category}(OTF2_{category}ReaderCallbacks* c) {{\n"
            + "\n".join(registers)
            + "\n}"
        )
    generated.write_text("\n".join(callbacks + registrations))
    (BUILD / "schema.json").write_text(json.dumps(schema, indent=2))
    marker = pre / "viewer-capabilities.json"
    capabilities = (
        json.loads(marker.read_text()) if marker.exists() else dict(extension=None)
    )
    capabilities["typedEvents"] = [
        key.split(":", 1)[1]
        for key in schema
        if key.startswith("GlobalEvt:") and key != "GlobalEvt:Unknown"
    ]
    enum_src = "\n".join(p.read_text() for p in inc.glob("*.h"))
    constants = sorted(
        set(
            re.findall(
                r"\b(OTF2_(?:PARADIGM|REGION_ROLE|LOCATION_TYPE|LOCATION_GROUP_TYPE|GROUP_TYPE|COLLECTIVE_OP|METRIC_|IO_OPERATION_MODE|TYPE_|MARKER_SEVERITY|RECORDER_KIND)[A-Z0-9_]*)\s*=",
                enum_src,
            )
        )
    )
    enum_c = BUILD / "enums.c"
    enum_c.write_text(
        '#include <otf2/otf2.h>\n#include <stdio.h>\nint main(){ puts("{");\n'
        + "\n".join(
            'printf("\\"'
            + n
            + '\\":%d'
            + ("," if i < len(constants) - 1 else "")
            + '\\n", (int)'
            + n
            + ");"
            for i, n in enumerate(constants)
        )
        + 'puts("}");}\n'
    )
    subprocess.run(
        [
            "gcc",
            str(enum_c),
            "-I" + str(pre / "include"),
            "-o",
            str(BUILD / "enums"),
        ],
        check=True,
    )
    (BUILD / "enums.json").write_bytes(subprocess.check_output([str(BUILD / "enums")]))
    temporary = out.with_suffix(".tmp")
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-O3",
            "-Wall",
            "-Wextra",
            "-Wno-unused-parameter",
            str(SOURCE / "reader.c"),
            "-I" + str(BUILD),  # generated callbacks.inc
            "-I" + str(pre / "include"),
            "-L" + str(pre / "lib"),
            "-Wl,-rpath," + str(pre / "lib"),
            "-lotf2",
            "-o",
            str(temporary),
        ],
        check=True,
    )
    temporary.replace(out)
    (BUILD / "reader_capabilities.json").write_text(
        json.dumps(capabilities, indent=2) + "\n"
    )
    print(f"Built {out} with {len(schema)} typed callbacks from {pre}")


if __name__ == "__main__":
    build()
