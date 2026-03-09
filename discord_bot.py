import discord
from discord.ext import commands
from discord import app_commands
import anthropic
import os
import asyncio
import json
import base64
import aiohttp
from datetime import timedelta

# ==========================================
# ตั้งค่า Bot
# ==========================================
TOKEN = os.getenv("DISCORD_TOKEN")              # Discord Bot Token
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # Anthropic API Key

# ==========================================
# ตั้งค่าระบบสลิป (แก้ไขตรงนี้)
# ==========================================
PAYMENT_ROLE_NAME = "ชำระเงินแล้ว"      # ชื่อ Role ที่จะให้อัตโนมัติ
PAYMENT_LOG_CHANNEL = "payment-log"      # ชื่อ channel สำหรับ log (ถ้ามี)
REQUIRED_AMOUNT = None                   # กำหนดยอดเงินขั้นต่ำ เช่น 299.0 หรือ None = ไม่จำกัด
RECIPIENT_NAME = None                    # ชื่อผู้รับที่ถูกต้อง เช่น "นายสมชาย" หรือ None = ไม่ตรวจ

# เก็บ Transaction ID ที่ใช้แล้ว (ป้องกันสลิปซ้ำ)
used_transaction_ids: set[str] = set()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# เก็บประวัติแชทต่อ user (สำหรับ context)
chat_histories: dict[int, list] = {}


# ==========================================
# Events
# ==========================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} พร้อมใช้งานแล้ว!")
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="ดูแล Server | /help"
    ))


@bot.event
async def on_member_join(member: discord.Member):
    """ต้อนรับสมาชิกใหม่"""
    channel = member.guild.system_channel
    if channel:
        embed = discord.Embed(
            title=f"🎉 ยินดีต้อนรับ {member.display_name}!",
            description=f"ขอบคุณที่เข้าร่วม **{member.guild.name}** นะครับ!\nพิมพ์ `/help` เพื่อดูคำสั่งทั้งหมด",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    """แจ้งเมื่อสมาชิกออก"""
    channel = member.guild.system_channel
    if channel:
        embed = discord.Embed(
            title=f"👋 {member.display_name} ออกจาก Server แล้ว",
            color=discord.Color.red()
        )
        await channel.send(embed=embed)


# ==========================================
# 🤖 AI Chatbot Commands
# ==========================================
@bot.tree.command(name="chat", description="คุยกับ AI ฉลาด ๆ")
@app_commands.describe(message="ข้อความที่ต้องการส่งถึง AI")
async def chat(interaction: discord.Interaction, message: str):
    await interaction.response.defer()

    user_id = interaction.user.id
    if user_id not in chat_histories:
        chat_histories[user_id] = []

    # เพิ่มข้อความของ user
    chat_histories[user_id].append({"role": "user", "content": message})

    # จำกัดประวัติไม่เกิน 20 ข้อความ
    if len(chat_histories[user_id]) > 20:
        chat_histories[user_id] = chat_histories[user_id][-20:]

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system="คุณคือ AI ผู้ช่วยใน Discord Server ตอบเป็นภาษาไทยหรืออังกฤษตามที่ผู้ใช้พิมพ์ ตอบสั้น กระชับ เป็นมิตร",
            messages=chat_histories[user_id]
        )

        ai_reply = response.content[0].text
        chat_histories[user_id].append({"role": "assistant", "content": ai_reply})

        embed = discord.Embed(
            description=ai_reply,
            color=discord.Color.blue()
        )
        embed.set_author(name="🤖 AI Assistant")
        embed.set_footer(text=f"ถามโดย {interaction.user.display_name} | /clear_chat เพื่อเคลียร์ประวัติ")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")


@bot.tree.command(name="clear_chat", description="เคลียร์ประวัติการคุยกับ AI ของคุณ")
async def clear_chat(interaction: discord.Interaction):
    chat_histories.pop(interaction.user.id, None)
    await interaction.response.send_message("🧹 เคลียร์ประวัติแชทเรียบร้อยแล้ว!", ephemeral=True)


# ==========================================
# 🛡️ Moderation Commands
# ==========================================
def is_mod():
    """Check ว่ามี permission Manage Members"""
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.manage_messages
    return app_commands.check(predicate)


@bot.tree.command(name="kick", description="[MOD] เตะสมาชิกออกจาก Server")
@app_commands.describe(member="สมาชิกที่ต้องการเตะ", reason="เหตุผล")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ ไม่สามารถเตะสมาชิกที่มี role สูงกว่าหรือเท่ากับคุณได้", ephemeral=True)
        return
    await member.kick(reason=reason)
    embed = discord.Embed(
        title="👢 Kick สมาชิก",
        description=f"**{member.display_name}** ถูกเตะออกจาก Server\n**เหตุผล:** {reason}",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"โดย {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ban", description="[MOD] แบนสมาชิกออกจาก Server")
@app_commands.describe(member="สมาชิกที่ต้องการแบน", reason="เหตุผล")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "ไม่ระบุเหตุผล"):
    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ ไม่สามารถแบนสมาชิกที่มี role สูงกว่าหรือเท่ากับคุณได้", ephemeral=True)
        return
    await member.ban(reason=reason)
    embed = discord.Embed(
        title="🔨 Ban สมาชิก",
        description=f"**{member.display_name}** ถูกแบนจาก Server\n**เหตุผล:** {reason}",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"โดย {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unban", description="[MOD] ยกเลิกการแบนสมาชิก")
@app_commands.describe(user_id="User ID ของสมาชิกที่ต้องการ unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Unban **{user.name}** เรียบร้อยแล้ว")
    except Exception as e:
        await interaction.response.send_message(f"❌ ไม่สามารถ unban ได้: {e}", ephemeral=True)


@bot.tree.command(name="timeout", description="[MOD] ปิดเสียง/พิมพ์สมาชิกชั่วคราว")
@app_commands.describe(member="สมาชิกที่ต้องการ timeout", minutes="จำนวนนาที", reason="เหตุผล")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int = 5, reason: str = "ไม่ระบุเหตุผล"):
    duration = timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(
        title="🔇 Timeout สมาชิก",
        description=f"**{member.display_name}** ถูก timeout {minutes} นาที\n**เหตุผล:** {reason}",
        color=discord.Color.yellow()
    )
    embed.set_footer(text=f"โดย {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="purge", description="[MOD] ลบข้อความในห้องนี้")
@app_commands.describe(amount="จำนวนข้อความที่ต้องการลบ (สูงสุด 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int = 10):
    amount = min(amount, 100)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🗑️ ลบข้อความ {len(deleted)} ข้อความเรียบร้อยแล้ว", ephemeral=True)


@bot.tree.command(name="userinfo", description="ดูข้อมูลของสมาชิก")
@app_commands.describe(member="สมาชิกที่ต้องการดูข้อมูล (ว่างไว้ = ดูตัวเอง)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(
        title=f"👤 ข้อมูลของ {member.display_name}",
        color=member.color
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Username", value=str(member), inline=True)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="เข้าร่วม Server", value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="สร้างบัญชี", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "ไม่มี", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="ดูข้อมูลของ Server")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"🏰 {guild.name}", color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="👑 เจ้าของ", value=guild.owner.mention, inline=True)
    embed.add_field(name="👥 สมาชิก", value=guild.member_count, inline=True)
    embed.add_field(name="💬 ห้อง", value=len(guild.channels), inline=True)
    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="📅 สร้างเมื่อ", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    await interaction.response.send_message(embed=embed)


# ==========================================
# 🧾 Slip Verification System
# ==========================================
async def analyze_slip_with_ai(image_data: bytes, media_type: str) -> dict:
    """ส่งรูปสลิปไปให้ Claude วิเคราะห์ และคืนค่าเป็น JSON"""
    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    prompt = """วิเคราะห์สลิปโอนเงินในรูปภาพนี้ แล้วตอบกลับเป็น JSON เท่านั้น ไม่ต้องมีข้อความอื่น

รูปแบบ JSON ที่ต้องการ:
{
  "is_valid_slip": true/false,
  "sender_name": "ชื่อผู้โอน หรือ null ถ้าไม่พบ",
  "recipient_name": "ชื่อผู้รับ หรือ null ถ้าไม่พบ",
  "amount": 000.00,
  "currency": "THB",
  "datetime": "วันที่และเวลา เช่น 25/12/2024 14:30 หรือ null ถ้าไม่พบ",
  "transaction_id": "เลขที่อ้างอิง/Transaction ID หรือ null ถ้าไม่พบ",
  "bank": "ชื่อธนาคาร หรือ null ถ้าไม่พบ",
  "notes": "หมายเหตุเพิ่มเติม ถ้ามี เช่น สลิปไม่ชัด สลิปปลอม ฯลฯ"
}

หากไม่ใช่สลิปโอนเงิน ให้ตั้ง is_valid_slip เป็น false"""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    # ลบ markdown code block ถ้ามี
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


async def get_or_create_role(guild: discord.Guild, role_name: str) -> discord.Role:
    """หา Role ที่มีอยู่ หรือสร้างใหม่ถ้ายังไม่มี"""
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(
            name=role_name,
            color=discord.Color.gold(),
            reason="สร้างโดยระบบตรวจสอบสลิปอัตโนมัติ"
        )
    return role


@bot.tree.command(name="verify_slip", description="ส่งสลิปโอนเงินเพื่อยืนยันการชำระเงิน")
@app_commands.describe(slip="รูปสลิปโอนเงิน (PNG, JPG)")
async def verify_slip(interaction: discord.Interaction, slip: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    # ตรวจสอบว่าเป็นไฟล์รูปภาพ
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    content_type = slip.content_type or ""
    if not any(ct in content_type for ct in ["image/png", "image/jpeg", "image/webp"]):
        await interaction.followup.send("❌ กรุณาส่งไฟล์รูปภาพ (PNG, JPG, WEBP) เท่านั้น", ephemeral=True)
        return

    # ตรวจสอบขนาดไฟล์ (max 10MB)
    if slip.size > 10 * 1024 * 1024:
        await interaction.followup.send("❌ ไฟล์ขนาดใหญ่เกินไป (สูงสุด 10MB)", ephemeral=True)
        return

    # แสดงสถานะกำลังวิเคราะห์
    processing_embed = discord.Embed(
        title="🔍 กำลังวิเคราะห์สลิป...",
        description="AI กำลังตรวจสอบข้อมูลในสลิป กรุณารอสักครู่",
        color=discord.Color.yellow()
    )
    await interaction.followup.send(embed=processing_embed, ephemeral=True)

    try:
        # ดาวน์โหลดรูปสลิป
        async with aiohttp.ClientSession() as session:
            async with session.get(slip.url) as resp:
                image_data = await resp.read()

        # วิเคราะห์ด้วย AI
        media_type = content_type if content_type in allowed_types else "image/jpeg"
        result = await analyze_slip_with_ai(image_data, media_type)

        member = interaction.user
        guild = interaction.guild

        # ตรวจสอบว่าเป็นสลิปจริง
        if not result.get("is_valid_slip"):
            fail_embed = discord.Embed(
                title="❌ ไม่ใช่สลิปโอนเงิน",
                description=f"ไม่สามารถยืนยันได้ว่าเป็นสลิปโอนเงินจริง\n**หมายเหตุ:** {result.get('notes', '-')}",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=fail_embed)
            return

        # ตรวจสอบ Transaction ID ซ้ำ
        txn_id = result.get("transaction_id")
        if txn_id and txn_id in used_transaction_ids:
            dup_embed = discord.Embed(
                title="⚠️ สลิปซ้ำ!",
                description=f"Transaction ID `{txn_id}` ถูกใช้งานไปแล้ว\nไม่สามารถใช้สลิปเดิมซ้ำได้",
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=dup_embed)
            return

        # ตรวจสอบจำนวนเงิน
        amount = result.get("amount", 0)
        if REQUIRED_AMOUNT and amount < REQUIRED_AMOUNT:
            amount_fail_embed = discord.Embed(
                title="❌ จำนวนเงินไม่ถึงที่กำหนด",
                description=f"ยอดเงินในสลิป: **{amount:,.2f} บาท**\nยอดที่ต้องการ: **{REQUIRED_AMOUNT:,.2f} บาท**",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=amount_fail_embed)
            return

        # ตรวจสอบชื่อผู้รับ
        if RECIPIENT_NAME:
            slip_recipient = result.get("recipient_name") or ""
            if RECIPIENT_NAME.lower() not in slip_recipient.lower():
                name_fail_embed = discord.Embed(
                    title="❌ ชื่อผู้รับไม่ตรง",
                    description=f"ชื่อผู้รับในสลิป: **{slip_recipient or 'ไม่พบข้อมูล'}**\nชื่อผู้รับที่ถูกต้อง: **{RECIPIENT_NAME}**",
                    color=discord.Color.red()
                )
                await interaction.edit_original_response(embed=name_fail_embed)
                return

        # ✅ สลิปผ่านการตรวจสอบทั้งหมด
        if txn_id:
            used_transaction_ids.add(txn_id)

        # ให้ Role อัตโนมัติ
        role = await get_or_create_role(guild, PAYMENT_ROLE_NAME)
        await member.add_roles(role, reason="ยืนยันการชำระเงินผ่านสลิป")

        # แสดงผลสำเร็จ
        success_embed = discord.Embed(
            title="✅ ยืนยันการชำระเงินสำเร็จ!",
            color=discord.Color.green()
        )
        success_embed.add_field(name="👤 ผู้โอน", value=result.get("sender_name") or "-", inline=True)
        success_embed.add_field(name="🏦 ผู้รับ", value=result.get("recipient_name") or "-", inline=True)
        success_embed.add_field(name="💰 จำนวนเงิน", value=f"{amount:,.2f} บาท", inline=True)
        success_embed.add_field(name="📅 วันที่/เวลา", value=result.get("datetime") or "-", inline=True)
        success_embed.add_field(name="🔖 Transaction ID", value=f"`{txn_id or '-'}`", inline=True)
        success_embed.add_field(name="🎖️ Role ที่ได้รับ", value=role.mention, inline=True)
        success_embed.set_footer(text=f"ยืนยันโดย AI | {member.display_name}")
        await interaction.edit_original_response(embed=success_embed)

        # ส่ง log ไปยัง channel payment-log (ถ้ามี)
        log_channel = discord.utils.get(guild.text_channels, name=PAYMENT_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="🧾 บันทึกการชำระเงิน",
                color=discord.Color.green()
            )
            log_embed.set_thumbnail(url=member.display_avatar.url)
            log_embed.add_field(name="👤 สมาชิก", value=f"{member.mention} ({member.display_name})", inline=False)
            log_embed.add_field(name="ผู้โอน", value=result.get("sender_name") or "-", inline=True)
            log_embed.add_field(name="ผู้รับ", value=result.get("recipient_name") or "-", inline=True)
            log_embed.add_field(name="💰 จำนวน", value=f"{amount:,.2f} บาท", inline=True)
            log_embed.add_field(name="📅 วันที่/เวลา", value=result.get("datetime") or "-", inline=True)
            log_embed.add_field(name="🔖 Transaction ID", value=f"`{txn_id or '-'}`", inline=True)
            log_embed.add_field(name="🏦 ธนาคาร", value=result.get("bank") or "-", inline=True)
            log_embed.set_image(url=slip.url)
            await log_channel.send(embed=log_embed)

    except json.JSONDecodeError:
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="⚠️ วิเคราะห์ไม่สำเร็จ",
                description="AI ไม่สามารถอ่านข้อมูลจากสลิปได้ กรุณาลองใหม่หรือส่งรูปที่ชัดขึ้น",
                color=discord.Color.orange()
            )
        )
    except Exception as e:
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            )
        )


@bot.tree.command(name="set_payment", description="[MOD] ตั้งค่าระบบตรวจสอบสลิป")
@app_commands.describe(
    role_name="ชื่อ Role ที่จะให้เมื่อชำระเงิน",
    required_amount="ยอดเงินขั้นต่ำ (0 = ไม่จำกัด)",
    recipient_name="ชื่อผู้รับที่ถูกต้อง (ว่าง = ไม่ตรวจ)"
)
@app_commands.checks.has_permissions(manage_roles=True)
async def set_payment(
    interaction: discord.Interaction,
    role_name: str = None,
    required_amount: float = None,
    recipient_name: str = None
):
    global PAYMENT_ROLE_NAME, REQUIRED_AMOUNT, RECIPIENT_NAME
    changes = []
    if role_name:
        PAYMENT_ROLE_NAME = role_name
        changes.append(f"🎖️ Role: **{role_name}**")
    if required_amount is not None:
        REQUIRED_AMOUNT = required_amount if required_amount > 0 else None
        changes.append(f"💰 ยอดขั้นต่ำ: **{required_amount:,.2f} บาท**" if required_amount > 0 else "💰 ยอดขั้นต่ำ: **ไม่จำกัด**")
    if recipient_name is not None:
        RECIPIENT_NAME = recipient_name if recipient_name else None
        changes.append(f"👤 ผู้รับ: **{recipient_name}**" if recipient_name else "👤 ผู้รับ: **ไม่ตรวจสอบ**")

    embed = discord.Embed(
        title="⚙️ อัปเดตการตั้งค่าระบบสลิป",
        description="\n".join(changes) if changes else "ไม่มีการเปลี่ยนแปลง",
        color=discord.Color.blurple()
    )
    embed.add_field(name="สถานะปัจจุบัน", value=(
        f"🎖️ Role: `{PAYMENT_ROLE_NAME}`\n"
        f"💰 ยอดขั้นต่ำ: `{f'{REQUIRED_AMOUNT:,.2f} บาท' if REQUIRED_AMOUNT else 'ไม่จำกัด'}`\n"
        f"👤 ผู้รับ: `{RECIPIENT_NAME or 'ไม่ตรวจสอบ'}`"
    ), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clear_transactions", description="[MOD] ล้างรายการ Transaction ID ที่ใช้แล้ว")
@app_commands.checks.has_permissions(manage_roles=True)
async def clear_transactions(interaction: discord.Interaction):
    count = len(used_transaction_ids)
    used_transaction_ids.clear()
    await interaction.response.send_message(
        f"🗑️ ล้าง Transaction ID {count} รายการเรียบร้อยแล้ว",
        ephemeral=True
    )


# ==========================================
# 📋 Help Command
# ==========================================
@bot.tree.command(name="help", description="ดูคำสั่งทั้งหมด")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 คำสั่งทั้งหมด",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="🤖 AI Chatbot",
        value="`/chat` - คุยกับ AI\n`/clear_chat` - เคลียร์ประวัติแชท",
        inline=False
    )
    embed.add_field(
        name="🧾 ระบบสลิป",
        value="`/verify_slip` - ส่งสลิปยืนยันการชำระเงิน\n`/set_payment` - [MOD] ตั้งค่าระบบสลิป\n`/clear_transactions` - [MOD] ล้างรายการ Transaction ID",
        inline=False
    )
    embed.add_field(
        name="🛡️ Moderation (ต้องการ Permission)",
        value="`/kick` - เตะสมาชิก\n`/ban` - แบนสมาชิก\n`/unban` - ยกเลิกแบน\n`/timeout` - timeout สมาชิก\n`/purge` - ลบข้อความ",
        inline=False
    )
    embed.add_field(
        name="ℹ️ ข้อมูล",
        value="`/userinfo` - ดูข้อมูลสมาชิก\n`/serverinfo` - ดูข้อมูล Server\n`/help` - ดูคำสั่งทั้งหมด",
        inline=False
    )
    await interaction.response.send_message(embed=embed)


# ==========================================
# Error Handler
# ==========================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {error}", ephemeral=True)


# ==========================================
# รัน Bot
# ==========================================
if __name__ == "__main__":
    bot.run(TOKEN)
