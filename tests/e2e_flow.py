"""
Prueba de punta a punta contra un backend local. Ver tests/README.md para levantarlo:
Postgres en Docker (tandas-test-pg:55432), mock_storage.py en el 8799 y uvicorn en el 8765.
"""
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://localhost:8765/api/v1"
created_files = []
failures = []


def call(method, path, token=None, json_body=None, form=None, raw=None, content_type=None):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body.decode(errors="replace")


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  -> {extra}" if not cond and extra else ""))
    if not cond:
        failures.append(name)


def expect(name, result, code):
    status, body = result
    check(f"{name} [{code}]", status == code, f"{status} {body}")
    return body


def register(name):
    phone = "55" + "".join(random.choice("0123456789") for _ in range(8))
    body = expect(f"registro {name}", call("POST", "/auth/register", json_body={
        "phone": phone, "full_name": name, "password": "secreto123"}), 201)
    return body["access_token"], body["user"]["id"]


def upload(token, content_type="image/png", filename="r.png", payload=b"\x89PNG fake"):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", "/upload/receipt", token=token, raw=body,
                content_type=f"multipart/form-data; boundary={boundary}")


def pay(token, round_id, name):
    res = upload(token)
    if res[0] == 201:
        created_files.append(res[1]["filename"])
    url = res[1]["url"]
    return expect(f"aportación {name}", call("POST", f"/payments/round/{round_id}/submit", token,
                                             json_body={"proof_image_url": url}), 201)


def detail(token, tanda_id):
    return call("GET", f"/tandas/{tanda_id}", token)[1]


org, org_id = register("Organizadora")
ana, ana_id = register("Ana")
beto, beto_id = register("Beto")
intruso, intruso_id = register("Intruso")

tanda = expect("crear tanda", call("POST", "/tandas", org, json_body={
    "title": "Prueba E2E", "contribution_amount": 200, "total_slots": 3,
    "frequency": "semanal", "assignment_method": "first_come"}), 201)
tid, code = tanda["id"], tanda["invite_code"]

d = detail(org, tid)
check("al crear, ninguna ronda recauda", all(r["status"] == "upcoming" for r in d["rounds"]))
check("en elección libre la organizadora no recibe número automático", all(s["user_id"] is None for s in d["slots"]))
expect("la organizadora elige el #1", call("POST", f"/slots/{d['slots'][0]['id']}/claim", org), 200)
expect("intruso no ve el detalle", call("GET", f"/tandas/{tid}", intruso), 404)
expect("intruso no ve los pagos", call("GET", f"/payments/tanda/{tid}", intruso), 404)

prev = expect("vista previa de la invitación", call("GET", f"/tandas/invite/{code.lower()}", ana), 200)
check("vista previa: lugares libres y sin ser miembro",
      not prev["already_member"] and [s["taken"] for s in prev["slots"]] == [True, False, False], prev)
check("vista previa: solo el nombre de pila", prev["slots"][0]["holder_first_name"] == "Organizadora"
      and "user" not in prev["slots"][0], prev["slots"][0])
expect("vista previa con código falso", call("GET", "/tandas/invite/TANDA-XXXXXX", ana), 404)
expect("vista previa sin sesión", call("GET", f"/tandas/invite/{code}"), 401)
expect("elección libre sin elegir número", call("POST", f"/tandas/join/{code}", ana), 400)
expect("elección libre sin elegir número (lista vacía)", call("POST", f"/tandas/join/{code}", ana,
                                                              json_body={"slot_numbers": []}), 400)
expect("número que no existe", call("POST", f"/tandas/join/{code}", ana, json_body={"slot_numbers": [9]}), 400)
expect("número ya apartado", call("POST", f"/tandas/join/{code}", ana, json_body={"slot_numbers": [1]}), 409)
check("el intento fallido no aparta nada", all(s["user_id"] is None for s in detail(org, tid)["slots"][1:]))
joined = expect("Ana se une con el #2", call("POST", f"/tandas/join/{code}", ana, json_body={"slot_numbers": [2]}), 200)
ana_slot = next(s["id"] for s in joined["slots"] if s["user_id"] == ana_id)
moved = expect("Ana se cambia al #3", call("POST", f"/slots/{ana_slot}/move", ana, json_body={"slot_number": 3}), 200)
check("ahora Ana tiene solo el #3", [s["slot_number"] for s in detail(org, tid)["slots"] if s["user_id"] == ana_id] == [3])
expect("cambiarse a un número ocupado", call("POST", f"/slots/{moved['id']}/move", ana, json_body={"slot_number": 1}), 409)
expect("cambiarse al mismo número", call("POST", f"/slots/{moved['id']}/move", ana, json_body={"slot_number": 3}), 400)
expect("otro no cambia el número de Ana", call("POST", f"/slots/{moved['id']}/move", intruso, json_body={"slot_number": 2}), 403)
expect("Ana regresa al #2", call("POST", f"/slots/{moved['id']}/move", ana, json_body={"slot_number": 2}), 200)
check("Ana quedó otra vez en el #2", [s["slot_number"] for s in detail(org, tid)["slots"] if s["user_id"] == ana_id] == [2])
check("Ana quedó en el #2", [s["slot_number"] for s in joined["slots"] if s["user_id"] == ana_id] == [2])
check("vista previa: Ana ya es miembro", call("GET", f"/tandas/invite/{code}", ana)[1]["already_member"])
expect("unirse otra vez no aparta más", call("POST", f"/tandas/join/{code}", ana, json_body={"slot_numbers": [3]}), 200)
check("Ana sigue con un solo número", sum(s["user_id"] == ana_id for s in detail(org, tid)["slots"]) == 1)
expect("sorteo en elección libre", call("POST", f"/tandas/{tid}/draw", org), 400)
expect("iniciar con lugares vacíos", call("POST", f"/tandas/{tid}/start", org), 400)
expect("Beto pide el número de Ana", call("POST", f"/tandas/join/{code}", beto, json_body={"slot_numbers": [2]}), 409)
expect("Beto se une con el #3", call("POST", f"/tandas/join/{code}", beto, json_body={"slot_numbers": [3]}), 200)
expect("tanda llena rechaza al intruso", call("POST", f"/tandas/join/{code}", intruso,
                                              json_body={"slot_numbers": [3]}), 400)
expect("editar no se permite a Ana", call("PATCH", f"/tandas/{tid}", ana, json_body={"title": "X"}), 403)
expect("bajar lugares con números apartados", call("PATCH", f"/tandas/{tid}", org, json_body={"total_slots": 2}), 400)
expect("Ana no puede iniciar", call("POST", f"/tandas/{tid}/start", ana), 403)

r1 = d["rounds"][0]["id"]
expect("no se aporta antes de iniciar", call("POST", f"/payments/round/{r1}/submit", ana,
                                             json_body={"proof_image_url": "/uploads/receipt_x.png"}), 400)

started = expect("organizadora inicia", call("POST", f"/tandas/{tid}/start", org), 200)
check("tanda activa", started["status"] == "active", started["status"])
check("ronda 1 recaudando", [r["status"] for r in started["rounds"]] == ["collecting", "upcoming", "upcoming"])
expect("iniciar dos veces", call("POST", f"/tandas/{tid}/start", org), 400)
expect("sorteo con tanda iniciada", call("POST", f"/tandas/{tid}/draw", org), 400)
expect("editar con tanda iniciada", call("PATCH", f"/tandas/{tid}", org, json_body={"title": "X"}), 400)
expect("eliminar con tanda iniciada", call("DELETE", f"/tandas/{tid}", org), 400)
slot_ids = {s["slot_number"]: s["id"] for s in started["slots"]}
expect("liberar turno con tanda iniciada", call("POST", f"/slots/{slot_ids[2]}/release", ana), 400)
expect("reasignar turno con tanda iniciada",
       call("PUT", f"/slots/{slot_ids[2]}/assign-user?user_id={beto_id}", org), 400)

# Subidas
expect("subir sin sesión", upload(None), 401)
expect("subir HTML", upload(ana, "text/html", "x.html", b"<script>alert(1)</script>"), 400)
expect("subir comprobante falso", call("POST", f"/payments/round/{r1}/submit", ana,
                                       json_body={"proof_image_url": "https://evil.example/x.png"}), 400)

for rnd_index in range(3):
    d = detail(org, tid)
    rnd = d["rounds"][rnd_index]
    check(f"ronda {rnd_index + 1} recaudando", rnd["status"] == "collecting", rnd["status"])
    p_org = pay(org, rnd["id"], f"organizadora r{rnd_index + 1}")
    p_ana = pay(ana, rnd["id"], f"Ana r{rnd_index + 1}")
    p_beto = pay(beto, rnd["id"], f"Beto r{rnd_index + 1}")
    if rnd_index == 0:
        check("la respuesta del pago trae al pagador", p_ana["payer"]["id"] == ana_id)
        expect("pagar dos veces la misma ronda", call("POST", f"/payments/round/{rnd['id']}/submit", ana,
                                                      json_body={"proof_image_url": "/uploads/receipt_y.png"}), 400)
        expect("intruso no puede aportar", call("POST", f"/payments/round/{rnd['id']}/submit", intruso,
                                                json_body={"proof_image_url": "/uploads/receipt_y.png"}), 403)
        expect("Ana no puede aprobar", call("POST", f"/payments/{p_beto['id']}/review", ana,
                                            json_body={"approved": True}), 403)

    beneficiary_slot = slot_ids[rnd["slot_number_beneficiary"]]
    beneficiary_token = {1: org, 2: ana, 3: beto}[rnd["slot_number_beneficiary"]]
    expect("confirmar bolsa antes de juntar todo", call("POST", f"/slots/{beneficiary_slot}/confirm-payout",
                                                        beneficiary_token), 400)

    for p in (p_org, p_ana, p_beto):
        expect("aprobar", call("POST", f"/payments/{p['id']}/review", org, json_body={"approved": True}), 200)
    if rnd_index == 0:
        import os
        listed = call("GET", f"/payments/tanda/{tid}", ana)[1]
        proofs = [p["proof_image_url"] for p in listed]
        if os.environ.get("STORAGE_MODE"):
            check("comprobantes con URL firmada", all(u and "/storage/v1/object/sign/comprobantes/receipt_" in u
                                                      and "token=" in u for u in proofs), proofs[:1])
        else:
            check("comprobantes locales", all(u and u.startswith("/uploads/receipt_") for u in proofs), proofs[:1])
        expect("aprobar dos veces", call("POST", f"/payments/{p_ana['id']}/review", org,
                                         json_body={"approved": True}), 400)

    d = detail(org, tid)
    rnd = d["rounds"][rnd_index]
    check(f"ronda {rnd_index + 1} completa", rnd["status"] == "completed_pending_payout" and
          rnd["collected_amount"] == 600, f"{rnd['status']} {rnd['collected_amount']}")
    other_token = ana if beneficiary_token is not ana else beto
    expect("otro no confirma la bolsa ajena", call("POST", f"/slots/{beneficiary_slot}/confirm-payout",
                                                   other_token), 403)
    confirmed = expect("beneficiario confirma", call("POST", f"/slots/{beneficiary_slot}/confirm-payout",
                                                     beneficiary_token), 200)
    check("la respuesta del turno trae al usuario", confirmed.get("user") is not None)

d = detail(org, tid)
check("tanda completada", d["status"] == "completed", d["status"])
check("todas las rondas cerradas", all(r["status"] == "closed" for r in d["rounds"]))
me = call("GET", "/users/me", ana)[1]
check("Ana suma una tanda completada", me["tandas_completed"] == 1, me["tandas_completed"])

listing = call("GET", "/tandas", ana)[1]
mine = next(t for t in listing if t["id"] == tid)
check("listado: mis números", mine["my_slot_numbers"] == [2], mine["my_slot_numbers"])
check("listado: sin ronda activa al terminar", mine["current_round_number"] is None)

# --- Editar y eliminar una tanda que no ha iniciado (sorteo) ---
import datetime as dt
hoy_mx = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)).date()
ayer = dt.datetime.combine(hoy_mx - dt.timedelta(days=1), dt.time(12), dt.timezone(dt.timedelta(hours=-6)))
expect("crear con fecha de inicio pasada", call("POST", "/tandas", org, json_body={
    "title": "Pasada", "contribution_amount": 100, "total_slots": 4, "start_date": ayer.isoformat()}), 400)
expect("crear con 1 lugar", call("POST", "/tandas", org, json_body={
    "title": "Mini", "contribution_amount": 100, "total_slots": 1}), 422)
inicio = dt.datetime(hoy_mx.year + 1, 1, 10, 12, tzinfo=dt.timezone(dt.timedelta(hours=-6)))
t2 = expect("crear tanda con sorteo y fecha de inicio", call("POST", "/tandas", org, json_body={
    "title": "Sorteo", "contribution_amount": 100, "total_slots": 4, "frequency": "semanal",
    "assignment_method": "draw", "start_date": inicio.isoformat()}), 201)
t2id, code2 = t2["id"], t2["invite_code"]
d2 = detail(org, t2id)
check("primer corte en la fecha de inicio", d2["slots"][0]["scheduled_payout_date"].startswith(f"{hoy_mx.year + 1}-01-10"),
      d2["slots"][0]["scheduled_payout_date"])
j = expect("en sorteo se entra sin elegir número", call("POST", f"/tandas/join/{code2}", ana), 200)
check("en sorteo toma el primer lugar libre", [s["slot_number"] for s in j["slots"] if s["user_id"] == ana_id] == [2])
expect("en sorteo los números elegidos se ignoran", call("POST", f"/tandas/join/{code2}", beto,
                                                         json_body={"slot_numbers": [4]}), 200)
check("Beto quedó en el #3", [s["slot_number"] for s in detail(org, t2id)["slots"] if s["user_id"] == beto_id] == [3])

edited = expect("editar la tanda", call("PATCH", f"/tandas/{t2id}", org, json_body={
    "title": "Sorteo navideño", "description": "Para regalos", "contribution_amount": 250,
    "total_slots": 6, "frequency": "quincenal"}), 200)
check("editar: datos nuevos", edited["title"] == "Sorteo navideño" and edited["description"] == "Para regalos"
      and edited["frequency"] == "quincenal", edited["title"])
check("editar: bolsa recalculada", edited["payout_total"] == 1500 and all(r["expected_amount"] == 1500 for r in edited["rounds"]),
      edited["payout_total"])
check("editar: 6 turnos y 6 rondas", [s["slot_number"] for s in edited["slots"]] == [1, 2, 3, 4, 5, 6]
      and [r["round_number"] for r in edited["rounds"]] == [1, 2, 3, 4, 5, 6])
check("editar: los apartados se conservan", [s["user_id"] for s in edited["slots"][:3]] == [org_id, ana_id, beto_id])
check("editar: fechas quincenales desde el inicio",
      [s["scheduled_payout_date"][:10] for s in edited["slots"][:2]] == [f"{hoy_mx.year + 1}-01-15", f"{hoy_mx.year + 1}-01-31"],
      [s["scheduled_payout_date"] for s in edited["slots"][:2]])
check("editar: rondas con las mismas fechas que los turnos",
      [r["due_date"] for r in edited["rounds"]] == [s["scheduled_payout_date"] for s in edited["slots"]])
shrunk = expect("bajar a 4 lugares (los quitados están libres)", call("PATCH", f"/tandas/{t2id}", org,
                                                                      json_body={"total_slots": 4}), 200)
check("bajar: quedan 4", len(shrunk["slots"]) == 4 and len(shrunk["rounds"]) == 4 and shrunk["payout_total"] == 1000)
check("editar sin descripción la conserva", shrunk["description"] == "Para regalos")
expect("editar con fecha pasada", call("PATCH", f"/tandas/{t2id}", org, json_body={"start_date": ayer.isoformat()}), 400)
expect("editar con monto cero", call("PATCH", f"/tandas/{t2id}", org, json_body={"contribution_amount": 0}), 422)
expect("Ana no elimina", call("DELETE", f"/tandas/{t2id}", ana), 403)
expect("intruso no elimina", call("DELETE", f"/tandas/{t2id}", intruso), 403)
expect("eliminar la tanda", call("DELETE", f"/tandas/{t2id}", org), 204)
expect("la tanda eliminada ya no existe", call("GET", f"/tandas/{t2id}", org), 404)
check("ya no aparece en el listado de Ana", all(t["id"] != t2id for t in call("GET", "/tandas", ana)[1]))
expect("su código ya no sirve", call("GET", f"/tandas/invite/{code2}", beto), 404)

# --- Entrar con huella (llave de dispositivo) ---
dev = expect("activar huella", call("POST", "/auth/devices", org, json_body={"device_name": "Xiaomi"}), 201)
logged = expect("entrar con huella", call("POST", "/auth/device-login", json_body={
    "device_id": dev["device_id"], "device_secret": dev["device_secret"]}), 200)
check("la huella entra como la organizadora", logged["user"]["id"] == org_id)
expect("huella con secreto falso", call("POST", "/auth/device-login", json_body={
    "device_id": dev["device_id"], "device_secret": "x" * 43}), 401)
expect("activar huella sin sesión", call("POST", "/auth/devices", json_body={"device_name": "X"}), 401)
expect("Beto no revoca la huella ajena (no hace nada)", call("DELETE", f"/auth/devices/{dev['device_id']}", beto), 204)
expect("la huella sigue sirviendo tras intento ajeno", call("POST", "/auth/device-login", json_body={
    "device_id": dev["device_id"], "device_secret": dev["device_secret"]}), 200)
expect("revocar mi huella", call("DELETE", f"/auth/devices/{dev['device_id']}", org), 204)
expect("huella revocada", call("POST", "/auth/device-login", json_body={
    "device_id": dev["device_id"], "device_secret": dev["device_secret"]}), 401)

# --- Recuperar contraseña con código del organizador ---
ana_phone = call("GET", "/users/me", ana)[1]["phone"]
ana_dev = expect("Ana activa huella", call("POST", "/auth/devices", ana, json_body={"device_name": "Moto"}), 201)
expect("Ana no genera códigos", call("POST", f"/tandas/{tid}/members/{beto_id}/reset-code", ana), 403)
expect("código para alguien fuera de la tanda", call("POST", f"/tandas/{tid}/members/{uuid.uuid4()}/reset-code", org), 404)
expect("código para uno mismo", call("POST", f"/tandas/{tid}/members/{org_id}/reset-code", org), 400)
rc = expect("código para Ana", call("POST", f"/tandas/{tid}/members/{ana_id}/reset-code", org), 200)
check("formato XXXX-XXXX", len(rc["code"]) == 9 and rc["code"][4] == "-", rc["code"])
expect("código equivocado", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": "AAAA-AAAA", "new_password": "nueva123"}), 400)
expect("usuario inexistente da el mismo error", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": "0000000000", "code": rc["code"], "new_password": "nueva123"}), 400)
expect("contraseña muy corta", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc["code"], "new_password": "123"}), 422)
reset = expect("restablecer con código (minúsculas y sin guion)", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc["code"].replace("-", "").lower(), "new_password": "nueva123"}), 200)
check("el restablecimiento deja la sesión iniciada", reset["user"]["id"] == ana_id and reset["access_token"])
expect("el código no se reutiliza", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc["code"], "new_password": "otra123"}), 400)
expect("login con la contraseña nueva", call("POST", "/auth/login", form={"username": ana_phone, "password": "nueva123"}), 200)
expect("login con la contraseña vieja", call("POST", "/auth/login", form={"username": ana_phone, "password": "secreto123"}), 401)
expect("restablecer revoca la huella de Ana", call("POST", "/auth/device-login", json_body={
    "device_id": ana_dev["device_id"], "device_secret": ana_dev["device_secret"]}), 401)

rc2 = expect("otro código para Ana", call("POST", f"/tandas/{tid}/members/{ana_id}/reset-code", org), 200)
for _ in range(5):
    call("POST", "/auth/reset-password", json_body={
        "phone_or_email": ana_phone, "code": "ZZZZ-ZZZZ", "new_password": "nueva456"})
expect("el código se quema tras 5 intentos", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc2["code"], "new_password": "nueva456"}), 400)
rc3 = expect("código nuevo", call("POST", f"/tandas/{tid}/members/{ana_id}/reset-code", org), 200)
expect("un código nuevo anula el anterior", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc2["code"], "new_password": "nueva456"}), 400)
expect("el código nuevo sí sirve", call("POST", "/auth/reset-password", json_body={
    "phone_or_email": ana_phone, "code": rc3["code"], "new_password": "nueva456"}), 200)

# --- Super admin y acciones a nombre de otros ---
import subprocess
admin, admin_id = register("Administrador")
check("sin permiso de admin al registrarse", call("GET", "/users/me", admin)[1]["is_superuser"] is False)
expect("no admin no ve todas las tandas", call("GET", "/tandas?all_tandas=true", admin), 403)
expect("no admin no busca personas", call("GET", "/admin/users?q=Ana", admin), 403)
subprocess.run(["docker", "exec", "tandas-test-pg", "psql", "-U", "postgres", "-qc",
                f"update users set is_superuser = true where id = '{admin_id}'"], check=True)
check("el admin se ve como admin", call("GET", "/users/me", admin)[1]["is_superuser"] is True)
todas = expect("admin ve todas las tandas", call("GET", "/tandas?all_tandas=true", admin), 200)
check("incluye tandas ajenas", any(t["id"] == tid for t in todas))
expect("admin ve el detalle de una tanda ajena", call("GET", f"/tandas/{tid}", admin), 200)
expect("admin ve los pagos de una tanda ajena", call("GET", f"/payments/tanda/{tid}", admin), 200)
check("el intruso no ve tandas ajenas en su lista", all(t["id"] != tid for t in call("GET", "/tandas", intruso)[1]))

t3 = expect("tanda para acciones a nombre de otros", call("POST", "/tandas", org, json_body={
    "title": "Tíos", "contribution_amount": 100, "total_slots": 3, "frequency": "semanal",
    "assignment_method": "first_come"}), 201)
t3id = t3["id"]
s3 = {s["slot_number"]: s["id"] for s in detail(org, t3id)["slots"]}
expect("la organizadora elige el #1 de Tíos", call("POST", f"/slots/{s3[1]}/claim", org), 200)
expect("Beto no asigna lugares", call("PUT", f"/slots/{s3[2]}/assign-user?user_id={ana_id}", beto), 403)
expect("admin mete a Ana en el #2", call("PUT", f"/slots/{s3[2]}/assign-user?user_id={ana_id}", admin), 200)
expect("admin mete a Beto en el #3", call("PUT", f"/slots/{s3[3]}/assign-user?user_id={beto_id}", admin), 200)
expect("admin edita una tanda ajena", call("PATCH", f"/tandas/{t3id}", admin, json_body={"title": "Tíos 2026"}), 200)
started3 = expect("admin inicia una tanda ajena", call("POST", f"/tandas/{t3id}/start", admin), 200)


def pay_for(token, round_id, payer_id, name):
    res = upload(token)
    created_files.append(res[1]["filename"])
    return call("POST", f"/payments/round/{round_id}/submit", token,
                json_body={"proof_image_url": res[1]["url"], "payer_user_id": payer_id})


for rnd_index, beneficiary_id in ((0, org_id), (1, ana_id)):
    rnd = detail(org, t3id)["rounds"][rnd_index]
    p_ana = expect(f"organizadora registra la aportación de Ana r{rnd_index + 1}",
                   pay_for(org, rnd["id"], ana_id, "Ana"), 201)
    check("la aportación queda a nombre de Ana", p_ana["payer_user_id"] == ana_id and p_ana["amount"] == 100)
    expect("no se registra dos veces a nombre de Ana", pay_for(org, rnd["id"], ana_id, "Ana"), 400)
    expect("Beto no registra aportaciones de otros", pay_for(beto, rnd["id"], org_id, "org"), 403)
    expect("no se registra a nombre de alguien sin número", pay_for(org, rnd["id"], intruso_id, "intruso"), 403)
    p_beto = expect(f"admin registra la aportación de Beto r{rnd_index + 1}", pay_for(admin, rnd["id"], beto_id, "Beto"), 201)
    p_org = pay(org, rnd["id"], f"organizadora t3 r{rnd_index + 1}")
    for p in (p_ana, p_beto, p_org):
        expect("admin aprueba en tanda ajena", call("POST", f"/payments/{p['id']}/review", admin,
                                                     json_body={"approved": True}), 200)
    slot_id = s3[rnd["slot_number_beneficiary"]]
    if beneficiary_id == org_id:
        expect("la organizadora confirma su bolsa", call("POST", f"/slots/{slot_id}/confirm-payout", org), 200)
    else:
        expect("Beto no confirma la bolsa de Ana", call("POST", f"/slots/{slot_id}/confirm-payout", beto), 403)
        expect("admin confirma la bolsa de Ana por ella", call("POST", f"/slots/{slot_id}/confirm-payout", admin), 200)
d3 = detail(org, t3id)
check("tras confirmar por Ana avanza a la ronda 3", [r["status"] for r in d3["rounds"]] == ["closed", "closed", "collecting"],
      [r["status"] for r in d3["rounds"]])

found = expect("admin busca personas", call("GET", "/admin/users?q=ana", admin), 200)
check("la búsqueda encuentra a Ana", any(u["id"] == ana_id for u in found))
org_phone = call("GET", "/users/me", org)[1]["phone"]
expect("no se repite un teléfono", call("PATCH", f"/admin/users/{ana_id}", admin, json_body={"phone": org_phone}), 400)
expect("teléfono inválido", call("PATCH", f"/admin/users/{ana_id}", admin, json_body={"phone": "123"}), 422)
expect("CLABE inválida", call("PATCH", f"/admin/users/{ana_id}", admin, json_body={"clabe": "12"}), 422)
nuevo_tel = "55" + "".join(random.choice("0123456789") for _ in range(8))
upd = expect("admin corrige datos de Ana", call("PATCH", f"/admin/users/{ana_id}", admin, json_body={
    "full_name": "Ana María", "phone": nuevo_tel, "clabe": "012180001234567899", "bank_name": "BBVA"}), 200)
check("datos corregidos", upd["full_name"] == "Ana María" and upd["phone"] == nuevo_tel and upd["bank_name"] == "BBVA")
expect("Ana entra con su teléfono nuevo", call("POST", "/auth/login", form={"username": nuevo_tel, "password": "nueva456"}), 200)
expect("Beto no corrige datos", call("PATCH", f"/admin/users/{ana_id}", beto, json_body={"full_name": "X"}), 403)
code_i = expect("admin genera código para alguien sin tanda", call("POST", f"/admin/users/{intruso_id}/reset-code", admin), 200)
check("código con formato", len(code_i["code"]) == 9)
expect("admin no genera código para sí", call("POST", f"/admin/users/{admin_id}/reset-code", admin), 400)
expect("Beto no genera códigos de admin", call("POST", f"/admin/users/{intruso_id}/reset-code", beto), 403)
expect("admin genera código desde una tanda ajena para quien no está en ella",
       call("POST", f"/tandas/{t3id}/members/{intruso_id}/reset-code", admin), 200)
expect("admin elimina una tanda ajena sin iniciar", call("DELETE", f"/tandas/{call('POST', '/tandas', org, json_body={'title': 'Borrar', 'contribution_amount': 100, 'total_slots': 2})[1]['id']}", admin), 204)

# --- Sorteo: números ocultos hasta llenar la tanda ---
t4 = expect("tanda por sorteo", call("POST", "/tandas", org, json_body={
    "title": "Sorteo real", "contribution_amount": 100, "total_slots": 3, "assignment_method": "draw"}), 201)
t4id, code4 = t4["id"], t4["invite_code"]
check("sin sorteo todavía", t4["numbers_drawn_at"] is None)
check("en sorteo la organizadora ya ocupa un lugar", detail(org, t4id)["slots"][0]["user_id"] == org_id)
expect("sorteo con lugares vacíos", call("POST", f"/tandas/{t4id}/draw", org), 400)
expect("Ana entra al sorteo", call("POST", f"/tandas/join/{code4}", ana), 200)
s4 = {s["slot_number"]: s["id"] for s in detail(org, t4id)["slots"]}
expect("en sorteo no hay cambio de número", call("POST", f"/slots/{s4[2]}/move", ana, json_body={"slot_number": 3}), 400)
expect("Beto entra al sorteo", call("POST", f"/tandas/join/{code4}", beto), 200)
expect("iniciar sin sorteo", call("POST", f"/tandas/{t4id}/start", org), 400)
expect("Ana no sortea", call("POST", f"/tandas/{t4id}/draw", ana), 403)
drawn = expect("sorteo con la tanda llena", call("POST", f"/tandas/{t4id}/draw", org), 200)
check("el sorteo queda registrado", drawn["numbers_drawn_at"] is not None)
check("el sorteo reparte a los mismos 3", sorted(s["user_id"] for s in drawn["slots"]) == sorted([org_id, ana_id, beto_id]))
expect("no se sortea dos veces", call("POST", f"/tandas/{t4id}/draw", org), 400)
expect("con sorteo ya se puede iniciar", call("POST", f"/tandas/{t4id}/start", org), 200)

t5 = expect("otra tanda por sorteo", call("POST", "/tandas", org, json_body={
    "title": "Sorteo editado", "contribution_amount": 100, "total_slots": 2, "assignment_method": "draw"}), 201)
call("POST", f"/tandas/join/{t5['invite_code']}", ana)
expect("sorteo de la tanda llena", call("POST", f"/tandas/{t5['id']}/draw", org), 200)
reopened = expect("agregar lugares tras el sorteo", call("PATCH", f"/tandas/{t5['id']}", org, json_body={"total_slots": 3}), 200)
check("agregar lugares anula el sorteo", reopened["numbers_drawn_at"] is None)
expect("eliminar la tanda de prueba", call("DELETE", f"/tandas/{t5['id']}", org), 204)

# --- Mi perfil: datos bancarios ---
perfil = expect("Beto pone su CLABE y banco", call("PUT", "/users/me", beto, json_body={
    "clabe": "012180001234567899", "bank_name": "BBVA"}), 200)
check("perfil guardado", perfil["clabe"] == "012180001234567899" and perfil["bank_name"] == "BBVA")
expect("CLABE con dígito verificador malo", call("PUT", "/users/me", beto, json_body={"clabe": "012180001234567890"}), 422)
expect("CLABE corta", call("PUT", "/users/me", beto, json_body={"clabe": "123"}), 422)
expect("nombre vacío", call("PUT", "/users/me", beto, json_body={"full_name": None}), 400)
call("PUT", "/users/me", org, json_body={"email": "org-e2e@example.com"})
expect("correo de otra cuenta", call("PUT", "/users/me", beto, json_body={"email": "org-e2e@example.com"}), 400)
expect("no puede volverse admin por su perfil", call("PUT", "/users/me", beto, json_body={"is_superuser": True}), 200)
check("sigue sin ser admin", call("GET", "/users/me", beto)[1]["is_superuser"] is False)
slot_beto = next(s for s in detail(org, tid)["slots"] if s["user_id"] == beto_id)
check("la CLABE se ve en la tanda para transferirle", slot_beto["user"]["clabe"] == "012180001234567899")

import os
if os.environ.get("STORAGE_MODE"):
    import time
    time.sleep(1)  # los avisos salen en segundo plano
    with urllib.request.urlopen("http://127.0.0.1:8799/_broadcasts") as res:
        msgs = json.loads(res.read())
    mine = [m for m in msgs if m["topic"] == f"tanda:{tid}"]
    check("avisos realtime al canal de la tanda", len(mine) >= 20, len(mine))
    check("avisos sin datos sensibles",
          all(set(m["payload"]) == {"tanda_id"} and m["event"] == "changed" for m in mine))
    print(f"     ({len(mine)} avisos enviados)")

print("\nARCHIVOS:" + ",".join(created_files))
print(f"\n{len(failures)} fallas" if failures else "\nTodo bien")
sys.exit(1 if failures else 0)
