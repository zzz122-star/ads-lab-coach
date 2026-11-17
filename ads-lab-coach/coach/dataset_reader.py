"""Run with ADS's Python, which includes the official dataset reader."""
import json
import sys


def read(path):
    import keysight.ads.dataset as ds
    with ds.open(path) as dataset:
        blocks = []
        for name in dataset:
            frame = dataset[name].to_dataframe().reset_index()
            if "freq" not in frame or "S[1,1]" not in frame:
                continue
            if frame["freq"].duplicated().any():
                raise ValueError("不支持含参数扫描的结果，请只运行单次频率扫描")
            frame = frame.sort_values("freq")
            block = {"freq": frame["freq"].tolist(), "variables": {}}
            for column in frame:
                if column.startswith(("S[", "PortZ[")):
                    block["variables"][column] = [[complex(v).real, complex(v).imag] for v in frame[column]]
            blocks.append(block)
        if len(blocks) != 1:
            raise ValueError("需要恰好一个包含 S11 的频率扫描结果")
        return blocks[0]


if __name__ == "__main__":
    try:
        print(json.dumps(read(sys.argv[1]), allow_nan=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True))
        sys.exit(1)
