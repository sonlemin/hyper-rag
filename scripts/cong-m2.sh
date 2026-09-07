#!/usr/bin/env bash
# Cong M2 (story 3.8): kich ban curl di het co che tren corpus that, chay lai duoc.
#
#   bash scripts/cong-m2.sh            # tren may chu, trong /root/hyper-rag-copilot
#   HYPER_RAG_API_URL=http://127.0.0.1:8000 bash scripts/cong-m2.sh
#
# Bay buoc, moi buoc in PASS/FAIL cho tung phep kiem, ma thoat khac 0 neu co
# mot FAIL. Thu tu la noi dung: buoc sau dung token va id cua buoc truoc.
#   B0 health
#   B1 dang nhap ba tai khoan seed, mot lan sai mat khau (DANG_NHAP_SAI)
#   B2 cung cau hoi hai vai: dev01 (devops) va ts01 (tech_support) deu tra loi,
#      ts01 co citation L1 mang masked_slots, dev01 nhieu L2 hon
#   B3 vai L0: ts01 hoi cau ma dap an nam o bi_mat_ha_tang -> tu choi, va than
#      tu choi bang tung byte voi than tu choi cua mot cau N7 (khong co dap an)
#   B4 hoan 4 bang chinh sach bang token admin, ts01 hoi lai cau ghim o moi bang,
#      roi ve day-du (trap EXIT cung ve day-du neu script chet giua chung)
#   B5 break-glass: ts01 xin mot hyperedge L1 -> demo01 duyet -> ts01 hoi lai,
#      citation goc len L2 chi con owner bi che -> don: cho grant het han
#   B6 doc audit_log: policy_swap, refusal kem ly_do, breakglass_*, query
#   B7 tran than request 64 KB: 413 THAN_QUA_LON (ADR-022 quyet dinh 1)
#
# Hai loai dong ket qua. PASS/FAIL la phep kiem **co che** (ma HTTP, hinh dang
# envelope, muc citation qua /do-thi, byte-identical, hang audit). QUAN SAT la
# thu phu thuoc dau ra LLM (answer khac nhau, so citation, dev01 tra loi duoc
# cau L0...): in ra de doc, khong lam FAIL, vi mot lan model chon dong khac la
# mot lan do gia. Rieng "ts01 tra loi duoc cau ghim voi citation L1 co masked_slots"
# la AC cua story nen van la FAIL.
#
# Secret khong nam trong file nay: mat khau doc tu .env goc repo theo ten bien
# DEMO_MAT_KHAU_<TAI KHOAN> (cung quy uoc voi config/tai-khoan.yaml), mat khau
# Postgres cung tu .env. May chu M2 phai chay HYPER_RAG_CHE_DO_DO=1: co tat thi
# B4 nhan 400 POLICY_CHI_CHE_DO_DO (ADR-022) va script noi ro phai bat gi.
#
# JSON doc bang python3 -c (co san tren Ubuntu 24.04), khong can jq. Khong goi
# module nao cua du an qua python: script chi noi HTTP va psql.
set -uo pipefail

REMOTE_DIR="${HYPER_RAG_REPO:-/root/hyper-rag-copilot}"
API="${HYPER_RAG_API_URL:-http://127.0.0.1:8000}"
POLICY_VAN_HANH="day-du"
BON_BANG="tat-phan-quyen nhi-phan day-du toi-thieu-l1"
# Cau ghim dung chung cho B2, B4, B5: da chay that o kiem tay 5.3 (goc la mot
# bao_cao_su_co L1 voi tech_support, cause bi che).
CAU_GHIM='Sự cố App01 lỗi 502 nguyên nhân là gì?'
# n5-05: dap an o bi_mat_ha_tang, L0 voi tech_support o day-du.
CAU_L0='Truy cập quản trị vào máy chủ sản xuất nội bộ đi qua đâu, và dải mạng quản trị là dải nào?'
# n7-06: khong co trong kho (neo_loai noi_bo:runbook), tu choi vi thieu thong tin.
CAU_N7='Tài khoản VPN của nhân viên nghỉ việc được lưu giữ bao lâu trước khi xóa hẳn?'

cd "$REMOTE_DIR" || { echo "khong vao duoc $REMOTE_DIR" >&2; exit 1; }
for f in .env .env.server; do
    [ -r "$f" ] || { echo "thieu $REMOTE_DIR/$f" >&2; exit 1; }
done
set -a
# shellcheck disable=SC1091
source .env
# shellcheck disable=SC1091
source .env.server
set +a

SO_FAIL=0
T0="$(date -u +%FT%TZ)"
pass() { echo "  PASS  $1"; }
quan_sat() { echo "  QUAN SAT  $1"; }
fail() { echo "  FAIL  $1" >&2; SO_FAIL=$((SO_FAIL + 1)); }
kiem() { if [ "$2" = "1" ]; then pass "$1"; else fail "$1"; fi; }
buoc() { echo; echo "== $1"; }

# Goi HTTP: in than roi dong cuoi la ma HTTP.
J() { curl -s -w '\n%{http_code}' -X "$1" "$API$2" -H 'content-type: application/json' ${3:+-H "authorization: Bearer $3"} ${4:+-d "$4"}; }
than() { echo "$1" | head -n -1; }
ma_http() { echo "$1" | tail -1; }
# Doc mot bieu thuc python tren than JSON (`d` la object).
py() { python3 -c 'import sys,json; d=json.load(sys.stdin); print('"$1"')' 2>/dev/null; }

PSQL="docker compose --env-file .env --env-file .env.server exec -T postgres psql -U ${POSTGRES_USER:-hyperrag} -d ${POSTGRES_DB:-hyperrag} -At -c"

TOKEN_ADMIN=""
GRANT_ID=""
don_dep() {
    # Ve bang van hanh du script chet o dau; cho grant cua lan chay nay het han
    # de lan chay ke khong bi 409 GRANT_CON_HAN.
    if [ -n "$TOKEN_ADMIN" ]; then
        J POST /admin/policy "$TOKEN_ADMIN" "{\"id\":\"$POLICY_VAN_HANH\"}" >/dev/null 2>&1 || true
    fi
    if [ -n "$GRANT_ID" ]; then
        $PSQL "UPDATE breakglass_grants SET expires_at = now() WHERE id = '$GRANT_ID'" >/dev/null 2>&1 || true
    fi
}
trap don_dep EXIT

buoc "B0 health"
R=$(curl -s -w '\n%{http_code}' "$API/health")
kiem "GET /health 200" "$([ "$(ma_http "$R")" = 200 ] && echo 1 || echo 0)"

buoc "B1 dang nhap"
dang_nhap() { J POST /auth/login "" "{\"tai_khoan\":\"$1\",\"mat_khau\":\"$2\"}"; }
TOKEN_TS=""; TOKEN_DEV=""; TOKEN_DEMO=""
for tk in ts01 dev01 demo01; do
    bien="DEMO_MAT_KHAU_$(echo "$tk" | tr '[:lower:]' '[:upper:]')"
    mk="${!bien:-}"
    [ -n "$mk" ] || { fail "thieu bien $bien trong .env"; continue; }
    R=$(dang_nhap "$tk" "$mk")
    tok=$(than "$R" | py 'd.get("token","")')
    kiem "dang nhap $tk 200 co token" "$([ "$(ma_http "$R")" = 200 ] && [ -n "$tok" ] && echo 1 || echo 0)"
    case $tk in ts01) TOKEN_TS=$tok;; dev01) TOKEN_DEV=$tok;; demo01) TOKEN_DEMO=$tok;; esac
done
TOKEN_ADMIN="$TOKEN_DEV"
R=$(dang_nhap ts01 "sai-mat-khau")
kiem "sai mat khau -> 401 DANG_NHAP_SAI" "$([ "$(ma_http "$R")" = 401 ] && [ "$(than "$R" | py 'd["error"]["code"]')" = DANG_NHAP_SAI ] && echo 1 || echo 0)"
[ -n "$TOKEN_TS" ] && [ -n "$TOKEN_DEV" ] && [ -n "$TOKEN_DEMO" ] || { echo "khong du token, dung" >&2; exit 1; }

hoi() { J POST /hoi-dap "$1" "{\"cau_hoi\":\"$2\"}"; }
# Kiem ma HTTP 200 cua mot luot hoi; khac 200 thi FAIL kem ma va code loi.
kiem_200() { local ma; ma=$(ma_http "$2"); if [ "$ma" = 200 ]; then return 0; fi; fail "$1: HTTP $ma $(than "$2" | py 'd.get("error",{}).get("code","")')"; return 1; }
# Muc cua mot hyperedge qua /do-thi (tat dinh, khong qua LLM): in "L1|cause,owner" hay "VANG".
muc_do_thi() { than "$(J POST /do-thi "$1" "{\"hyperedge_ids\":[\"$2\"]}")" | py '(lambda he,che: (he[0]["level"]+"|"+",".join(sorted(che))) if he else "VANG")([n for n in d["graph"]["nodes"] if n["kind"]=="hyperedge"], [n["id"].split("#")[1] for n in d["graph"]["nodes"] if n["kind"]=="entity" and n["masked"]])'; }
tom_tat() { python3 -c "import sys,json; d=json.load(sys.stdin); c=d['citations']; print('refused=%s citation=%d L1=%d L2=%d che=%d answer=%r' % (d['refused'], len(c), sum(x['level']=='L1' for x in c), sum(x['level']=='L2' for x in c), sum(bool(x['masked_slots']) for x in c), (d['answer'] or '')[:160]))"; }

buoc "B2 cung cau hoi, hai vai"
R_DEV=$(hoi "$TOKEN_DEV" "$CAU_GHIM"); T_DEV=$(than "$R_DEV")
R_TS=$(hoi "$TOKEN_TS" "$CAU_GHIM"); T_TS=$(than "$R_TS")
echo "  dev01: $(echo "$T_DEV" | tom_tat)"
echo "  ts01 : $(echo "$T_TS" | tom_tat)"
kiem_200 "dev01 hoi cau ghim" "$R_DEV" && kiem "dev01 tra loi (refused false)" "$([ "$(echo "$T_DEV" | py 'd["refused"]')" = False ] && echo 1 || echo 0)"
kiem_200 "ts01 hoi cau ghim" "$R_TS" && kiem "ts01 tra loi (khoan ledger co_no_answer)" "$([ "$(echo "$T_TS" | py 'd["refused"]')" = False ] && echo 1 || echo 0)"
kiem "ts01 co >=1 citation L1 mang masked_slots" "$([ "$(echo "$T_TS" | py 'sum(c["level"]=="L1" and bool(c["masked_slots"]) for c in d["citations"])')" -ge 1 ] 2>/dev/null && echo 1 || echo 0)"
kiem "moi citation cua ts01 mang du 6 khoa" "$([ "$(echo "$T_TS" | py 'all(set(c)=={"id","level","scope","content_type","masked_slots","owner_group"} for c in d["citations"])')" = True ] && echo 1 || echo 0)"
L2_DEV=$(echo "$T_DEV" | py 'sum(c["level"]=="L2" for c in d["citations"])'); L2_TS=$(echo "$T_TS" | py 'sum(c["level"]=="L2" for c in d["citations"])')
quan_sat "dev01 citation L2 = $L2_DEV, ts01 citation L2 = $L2_TS (tap dung do model chon)"
quan_sat "hai answer $([ "$(echo "$T_DEV" | py 'd["answer"]')" != "$(echo "$T_TS" | py 'd["answer"]')" ] && echo khac || echo giong) nhau"
kiem "meta.role khac nhau, khong truong nao khac ngoai 5 khoa" "$([ "$(echo "$T_TS" | py 'sorted(d)==["answer","citations","graph","meta","refused"] and d["meta"]["role"]=="tech_support"')" = True ] && echo 1 || echo 0)"
GOC=$(echo "$T_TS" | py 'next((c["id"] for c in d["citations"] if c["level"]=="L1" and c["masked_slots"]), "")')
if [ -z "$GOC" ]; then
    # Tap dung da thu hep theo `nguon` co the khong con muc L1: tra tap thay
    # (hang query moi nhat cua ts01 trong audit) roi hoi /do-thi de chon mot L1.
    IDS=$($PSQL "SELECT to_json(hyperedge_ids) FROM audit_log WHERE event='query' AND act='ts01' AND thoi_diem > '$T0' ORDER BY thoi_diem DESC LIMIT 1")
    [ -n "$IDS" ] && GOC=$(than "$(J POST /do-thi "$TOKEN_TS" "{\"hyperedge_ids\":$IDS}")" | py 'next((n["id"] for n in d["graph"]["nodes"] if n["kind"]=="hyperedge" and n["level"]=="L1"), "")')
fi
echo "  hyperedge L1 chon cho B5: ${GOC:-<khong co>}"

buoc "B3 vai L0 nhan template tu choi, bang tung byte voi tu choi khong-co-dap-an"
R_L0=$(hoi "$TOKEN_TS" "$CAU_L0"); T_L0=$(than "$R_L0")
R_N7=$(hoi "$TOKEN_TS" "$CAU_N7"); T_N7=$(than "$R_N7")
kiem_200 "ts01 hoi cau L0" "$R_L0"; kiem_200 "ts01 hoi cau N7" "$R_N7"
echo "  L0 : $(echo "$T_L0" | tom_tat)"
echo "  N7 : $(echo "$T_N7" | tom_tat)"
kiem "cau L0 -> refused true, answer null, citations []" "$([ "$(echo "$T_L0" | py 'd["refused"] is True and d["answer"] is None and d["citations"]==[]')" = True ] && echo 1 || echo 0)"
kiem "cau N7 -> refused true" "$([ "$(echo "$T_N7" | py 'd["refused"] is True')" = True ] && echo 1 || echo 0)"
kiem "hai than tu choi bang nhau tung byte" "$([ "$T_L0" = "$T_N7" ] && echo 1 || echo 0)"
quan_sat "dev01 hoi cung cau L0: refused=$(than "$(hoi "$TOKEN_DEV" "$CAU_L0")" | py 'd["refused"]') (khac nhau la do quyen)"

buoc "B4 hoan 4 bang chinh sach, khong sua code"
R=$(J GET /admin/policy "$TOKEN_ADMIN")
kiem "GET /admin/policy bang admin: dang chay $POLICY_VAN_HANH, danh muc 4" "$([ "$(than "$R" | py 'd["id"]=="'"$POLICY_VAN_HANH"'" and len(d["danh_muc"])==4')" = True ] && echo 1 || echo 0)"
R=$(J GET /admin/policy "$TOKEN_TS")
kiem "ts01 (khong admin) bi 403" "$([ "$(ma_http "$R")" = 403 ] && echo 1 || echo 0)"
declare -A L1_THEO_BANG
for ma in $BON_BANG; do
    R=$(J POST /admin/policy "$TOKEN_ADMIN" "{\"id\":\"$ma\"}")
    if [ "$(ma_http "$R")" != 200 ]; then
        fail "hoan sang $ma: HTTP $(ma_http "$R") $(than "$R" | py 'd["error"]["code"]') - neu POLICY_CHI_CHE_DO_DO thi bat HYPER_RAG_CHE_DO_DO=1 trong .env.server roi dung lai api"
        continue
    fi
    pass "hoan sang $ma 200, policy_version $(than "$R" | py 'd["policy_version"][:12]')"
    T=$(than "$(hoi "$TOKEN_TS" "$CAU_GHIM")")
    echo "    ts01 @ $ma: $(echo "$T" | tom_tat)"
    L1_THEO_BANG[$ma]=$(echo "$T" | py 'sum(c["level"]=="L1" for c in d["citations"])')
    case $ma in
        tat-phan-quyen) kiem "  tat-phan-quyen: moi citation L2, chi owner con bi che (AD-9)" "$([ "$(echo "$T" | py 'all(c["level"]=="L2" and set(c["masked_slots"])<={"owner"} for c in d["citations"]) and d["refused"] is False')" = True ] && echo 1 || echo 0)";;
        nhi-phan)       kiem "  nhi-phan: khong citation L1 (L1 ep xuong L0)" "$([ "${L1_THEO_BANG[$ma]:-x}" = 0 ] && echo 1 || echo 0)";;
        day-du)         kiem "  day-du: co citation L1" "$([ "${L1_THEO_BANG[$ma]:-0}" -ge 1 ] 2>/dev/null && echo 1 || echo 0)";;
        toi-thieu-l1)   quan_sat "  toi-thieu-l1: ts01 refused=$(echo "$T" | py 'd["refused"]'), L1=${L1_THEO_BANG[$ma]}";;
    esac
done
R=$(J POST /admin/policy "$TOKEN_ADMIN" "{\"id\":\"$POLICY_VAN_HANH\"}")
if [ "$(than "$R" | py 'd.get("id","")')" != "$POLICY_VAN_HANH" ]; then
    fail "ve $POLICY_VAN_HANH: HTTP $(ma_http "$R")"; echo "dung: B5 khong chay duoi mot bang do" >&2; exit 1
fi
pass "ve $POLICY_VAN_HANH"

buoc "B5 break-glass: xin -> duyet -> hoi lai -> don (muc kiem qua /do-thi, tat dinh)"
if [ -z "$GOC" ]; then
    fail "khong co hyperedge L1 nao cua ts01 de xin"
else
    kiem "truoc grant: /do-thi goc L1 co node che" "$([ "$(muc_do_thi "$TOKEN_TS" "$GOC" | cut -d'|' -f1)" = L1 ] && echo 1 || echo 0)"
    R=$(J POST /break-glass/yeu-cau "$TOKEN_TS" "{\"hyperedge_id\":\"$GOC\",\"ly_do\":\"cong M2 story 3.8\"}")
    if [ "$(ma_http "$R")" = 409 ] && [ "$(than "$R" | py 'd["error"]["code"]')" = GRANT_CON_HAN ]; then
        # Grant cua lan chay truoc con han: cho het han bang gio Postgres roi xin lai,
        # de mot lan PASS luon la mot lan da kiem break-glass.
        echo "  grant cu con han, cho het han roi xin lai"
        $PSQL "UPDATE breakglass_grants SET expires_at = now() WHERE act='ts01' AND space='synth' AND '$GOC' = ANY(hyperedge_ids) AND expires_at > now()" >/dev/null
        R=$(J POST /break-glass/yeu-cau "$TOKEN_TS" "{\"hyperedge_id\":\"$GOC\",\"ly_do\":\"cong M2 story 3.8\"}")
    fi
    MA=$(ma_http "$R")
    YC=$(than "$R" | py 'd.get("id","")')
    kiem "ts01 xin 201, id $YC, trang thai cho_duyet" "$([ "$MA" = 201 ] && [ "$(than "$R" | py 'd["trang_thai"]')" = cho_duyet ] && echo 1 || echo 0)"
    R=$(J GET /break-glass/hang-cho "$TOKEN_DEMO")
    kiem "demo01 (Tech Support) thay yeu cau tren hang cho" "$([ "$(than "$R" | py 'any(y["id"]=="'"$YC"'" for y in d["yeu_cau"])')" = True ] && echo 1 || echo 0)"
    R=$(J POST "/break-glass/yeu-cau/$YC/duyet" "$TOKEN_DEMO")
    GRANT_ID=$(than "$R" | py 'd["grant"]["id"]')
    kiem "demo01 duyet 200, grant $GRANT_ID cho (ts01, tech_support)" "$([ "$(ma_http "$R")" = 200 ] && [ "$(than "$R" | py 'd["grant"]["act"]=="ts01" and d["grant"]["role"]=="tech_support" and d["grant"]["hyperedge_ids"]==["'"$GOC"'"]')" = True ] && echo 1 || echo 0)"
    MUC_SAU=$(muc_do_thi "$TOKEN_TS" "$GOC")
    kiem "sau grant: /do-thi goc L2, chi owner con che ($MUC_SAU)" "$([ "$(echo "$MUC_SAU" | python3 -c 'import sys; s=sys.stdin.read().strip(); l,_,c=s.partition("|"); print(l=="L2" and set(filter(None,c.split(",")))<={"owner"})')" = True ] && echo 1 || echo 0)"
    kiem "dev01 /do-thi goc khong doi (grant khong lan vai khac)" "$([ "$(muc_do_thi "$TOKEN_DEV" "$GOC" | cut -d'|' -f1)" = L2 ] && echo 1 || echo 0)"
    R_SAU=$(hoi "$TOKEN_TS" "$CAU_GHIM"); T=$(than "$R_SAU")
    kiem_200 "ts01 hoi lai sau grant" "$R_SAU" && kiem "citation goc co mat va len L2" "$([ "$(echo "$T" | py 'next((c["level"] for c in d["citations"] if c["id"]=="'"$GOC"'"), "VANG")')" = L2 ] && echo 1 || echo 0)"
    echo "  ts01 sau grant: $(echo "$T" | tom_tat)"
    kiem "xin lai cung hyperedge -> 409 GRANT_CON_HAN" "$([ "$(than "$(J POST /break-glass/yeu-cau "$TOKEN_TS" "{\"hyperedge_id\":\"$GOC\",\"ly_do\":\"lan hai\"}")" | py 'd["error"]["code"]')" = GRANT_CON_HAN ] && echo 1 || echo 0)"
    $PSQL "UPDATE breakglass_grants SET expires_at = now() WHERE id = '$GRANT_ID'" >/dev/null
    kiem "sau het han: /do-thi goc ve L1 co node che" "$([ "$(muc_do_thi "$TOKEN_TS" "$GOC" | cut -d'|' -f1)" = L1 ] && echo 1 || echo 0)"
    GRANT_ID=""
fi

buoc "B6 audit_log (30 hang moi nhat cua cac su kien lien quan)"
$PSQL "SELECT to_char(thoi_diem,'HH24:MI:SS') AS luc, tier, event, coalesce(act,'-') AS act, coalesce(role,'-') AS role, coalesce(chi_tiet->>'ly_do', chi_tiet->>'policy_id_moi', chi_tiet->>'trang_thai', '') AS chi_tiet, array_length(hyperedge_ids,1) AS n_he FROM audit_log WHERE event IN ('query','refusal','policy_swap','filter','auth_login','breakglass_request','breakglass_approve','breakglass_cancel') ORDER BY thoi_diem DESC LIMIT 30" | sed 's/^/  /'
kiem "tu $T0: >=5 hang policy_swap cua dev01, >=2 refusal cua ts01 kem ly_do, >=1 breakglass_approve" "$([ "$($PSQL "SELECT count(*) FROM audit_log WHERE event='policy_swap' AND act='dev01' AND thoi_diem > '$T0'")" -ge 5 ] && [ "$($PSQL "SELECT count(*) FROM audit_log WHERE event='refusal' AND act='ts01' AND chi_tiet ? 'ly_do' AND thoi_diem > '$T0'")" -ge 2 ] && [ "$($PSQL "SELECT count(*) FROM audit_log WHERE event='breakglass_approve' AND thoi_diem > '$T0'")" -ge 1 ] && echo 1 || echo 0)"

buoc "B7 tran than request (ADR-022 quyet dinh 1)"
R=$(python3 -c 'import json; print(json.dumps({"cau_hoi": "a"*70000}))' | curl -s -w '\n%{http_code}' -X POST "$API/hoi-dap" -H "authorization: Bearer $TOKEN_TS" -H 'content-type: application/json' --data-binary @-)
kiem "than 70 KB -> 413 THAN_QUA_LON" "$([ "$(ma_http "$R")" = 413 ] && [ "$(than "$R" | py 'd["error"]["code"]')" = THAN_QUA_LON ] && echo 1 || echo 0)"
R=$(J GET /admin/policy "$TOKEN_ADMIN")
kiem "GET /admin/policy khai che_do_do=true (tien trinh do)" "$([ "$(than "$R" | py 'd.get("che_do_do")')" = True ] && echo 1 || echo 0)"

echo
if [ "$SO_FAIL" -eq 0 ]; then
    echo "CONG M2: PASS (0 FAIL)"
    exit 0
fi
echo "CONG M2: $SO_FAIL FAIL" >&2
exit 1
