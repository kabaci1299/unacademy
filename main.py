import os
import json
import requests
from datetime import datetime, time, timedelta
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from config import API_ID, API_HASH, BOT_TOKEN, AUTH_USERS

# Initialize bot
app = Client("SDV_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Constants
GOALS_API = "https://unknownkil.github.io/Goal_unad-json/goals.json"
BATCHES_API = "https://api-frontend.unacademy.com/api/v1/batch/lists/filter/?goal_uid={uid}&limit=10&offset={offset}&type=0"
UPDATE_API = "https://studyuk.fun/update-batch.php"
BATCH_INFO_API = "https://studyuk.fun/batch.json"
ADD_BATCH_API = "https://studyuk.fun/add_batch.php?batch_id={uid}"

# Cache for storing batch details
batch_cache = {}
bot_enabled = True  # Global bot state
user_request_counts = {}  # Track user requests per day
last_reset_time = datetime.now()  # Track when counts were last reset
all_users = set()  # Track all users who have interacted with the bot

# Helper functions
def reset_request_counts():
    global user_request_counts, last_reset_time
    now = datetime.now()
    if now.date() > last_reset_time.date():
        user_request_counts = {}
        last_reset_time = now

def can_make_request(user_id):
    reset_request_counts()
    return user_request_counts.get(user_id, 0) < 5

def increment_request_count(user_id):
    reset_request_counts()
    user_request_counts[user_id] = user_request_counts.get(user_id, 0) + 1

def get_goals_keyboard(page=0):
    try:
        with requests.get(GOALS_API) as response:
            goals = json.loads(response.text)

        total_goals = len(goals)
        start = page * 10
        end = min(start + 10, total_goals)

        keyboard = []
        for goal in goals[start:end]:
            keyboard.append([InlineKeyboardButton(goal["name"], callback_data=f"goal_{goal['uid']}_0")])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"goals_{page-1}"))
        if end < total_goals:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"goals_{page+1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        print(f"Error getting goals: {e}")
        return None

def get_batches_data(goal_uid, offset=0):
    try:
        response = requests.get(BATCHES_API.format(uid=goal_uid, offset=offset))
        response.raise_for_status()
        data = response.json()

        # Cache the batches data
        for batch in data.get("results", []):
            batch_cache[batch["uid"]] = batch

        return data
    except Exception as e:
        print(f"Error getting batches: {e}")
        return None

def get_batches_keyboard(goal_uid, offset=0):
    data = get_batches_data(goal_uid, offset)
    if not data or not data.get("results"):
        return None, None

    keyboard = []
    for batch in data["results"]:
        keyboard.append([InlineKeyboardButton(batch["name"], callback_data=f"batch_{batch['uid']}")])

    nav_buttons = []
    if data.get("previous"):
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"goal_{goal_uid}_{offset-10}"))
    if data.get("next"):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"goal_{goal_uid}_{offset+10}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    return InlineKeyboardMarkup(keyboard), data["results"]

def format_batch_info(batch, user):
    try:
        start_time = datetime.strptime(batch["starts_at"], "%Y-%m-%dT%H:%M:%SZ")
        ist_time = start_time.strftime("%d %b %Y, %I:%M %p IST")

        languages = ", ".join([lang["label"] for lang in batch.get("languages", [])])

        caption = f"""
📌 **Batch Name:** {batch['name']}
🎯 **Goal:** {batch['goal']['name']}
⏰ **Start Time:** {ist_time}
🌐 **Language(s):** {languages}
🔗 **Link:** [Click Here]({batch['permalink']})
        
👤 **Requested By:** {user.first_name}
🆔 **User ID:** `{user.id}`
"""
        if user.username:
            caption += f"📧 **Username:** @{user.username}\n"

        return caption
    except Exception as e:
        print(f"Error formatting batch info: {e}")
        return f"Error displaying batch information. Please try again."

def get_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("🎯 Goals", callback_data="show_goals_0")],
    ]

    if user_id in AUTH_USERS:
        keyboard.append([InlineKeyboardButton("🔄 Manual Update", callback_data="manual_update")])

    return InlineKeyboardMarkup(keyboard)

async def perform_batch_update():
    try:
        # Get batch data
        response = requests.get(BATCH_INFO_API)
        batches = response.json().get("batches", [])

        # Update each batch
        for batch in batches:
            batch_id = batch["batch_id"]
            payload = {"batch_id": batch_id}
            requests.post(UPDATE_API, json=payload)
            await asyncio.sleep(1)  # Add delay between requests

        return True, len(batches)
    except Exception as e:
        print(f"Error updating batches: {e}")
        return False, 0

async def auto_update_task():
    notification_sent = False
    
    while True:
        now = datetime.now()
        current_time = now.time()
        
        # Check if it's 11:55 AM IST (6:25 AM UTC)
        if current_time.hour == 6 and current_time.minute == 25 and not notification_sent:
            # Send notification to all users
            for user_id in all_users:
                try:
                    await app.send_message(
                        user_id,
                        "🔄 All batches will start updating in 5 minutes at 12:00 PM IST. Please wait..."
                    )
                except Exception as e:
                    print(f"Error sending update notification to user {user_id}: {e}")
            notification_sent = True
        
        # Check if it's 12:00 PM IST (6:30 AM UTC)
        if current_time.hour == 6 and current_time.minute == 30:
            success, count = await perform_batch_update()
            
            # Send completion notification to all users
            for user_id in all_users:
                try:
                    if success:
                        await app.send_message(
                            user_id,
                            f"✅ All batches update completed!\n\nSuccessfully updated {count} batches."
                        )
                    else:
                        await app.send_message(
                            user_id,
                            "❌ Batch update failed. Please try again later or contact admin."
                        )
                except Exception as e:
                    print(f"Error sending completion notification to user {user_id}: {e}")
            
            # Reset notification flag after 1 minute to avoid multiple triggers
            await asyncio.sleep(60)
            notification_sent = False
        
        await asyncio.sleep(30)  # Check every 30 seconds

async def add_batch_to_system(batch_uid, user):
    try:
        # First API call to update batch
        payload = {"batch_id": batch_uid}
        response = requests.post(UPDATE_API, json=payload)

        if response.status_code != 200:
            return False

        # Second API call to add batch
        response = requests.get(ADD_BATCH_API.format(uid=batch_uid))

        if response.status_code == 200:
            # Notify the user who requested this batch
            requester_id = None
            if isinstance(user, int):
                requester_id = user
            else:
                requester_id = user.id

            try:
                await app.send_message(
                    requester_id,
                    f"✅ Your requested batch ({batch_uid}) has been added to the system!"
                )
            except Exception as e:
                print(f"Error notifying user {requester_id}: {e}")

            return True
        return False
    except Exception as e:
        print(f"Error adding batch: {e}")
        return False

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    if not bot_enabled and message.from_user.id not in AUTH_USERS:
        await message.reply_text("❌ The bot is currently disabled. Only admins can use it.")
        return
    
    # Add user to all_users set
    all_users.add(message.from_user.id)

    keyboard = get_main_menu_keyboard(message.from_user.id)
    welcome_msg = "🎉 Welcome to SDV Bot!\n\n👇 Please select an option from the menu below:"
    await message.reply_text(welcome_msg, reply_markup=keyboard)

@app.on_message(filters.command("on") & filters.user(AUTH_USERS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled
    bot_enabled = True
    await message.reply_text("✅ Bot has been enabled for all users.")

@app.on_message(filters.command("off") & filters.user(AUTH_USERS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled
    bot_enabled = False
    await message.reply_text("❌ Bot has been disabled for regular users. Only admins can use it now.")

@app.on_message(filters.command("broadcast") & filters.user(AUTH_USERS))
async def broadcast_message(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide a message to broadcast\nUsage: `/broadcast your message`", parse_mode="markdown")
        return
    
    # Extract the broadcast message
    broadcast_text = message.text.split(' ', 1)[1]
    
    # Send to all users
    success_count = 0
    fail_count = 0
    
    for user_id in all_users:
        try:
            await app.send_message(user_id, f"📢 Broadcast Message:\n\n{broadcast_text}")
            success_count += 1
        except Exception as e:
            print(f"Error sending broadcast to user {user_id}: {e}")
            fail_count += 1
    
    await message.reply_text(f"✅ Broadcast completed!\n\nSuccess: {success_count}\nFailed: {fail_count}")

@app.on_message(filters.command("add") & filters.user(AUTH_USERS))
async def add_batch_command(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            await message.reply_text("❌ Please provide a batch ID\nUsage: `/add batch_id`", parse_mode="markdown")
            return

        batch_id = message.command[1]
        user = message.from_user

        # First API call to update batch
        update_payload = {"batch_id": batch_id}
        update_response = requests.post(UPDATE_API, json=update_payload)

        if update_response.status_code != 200:
            await message.reply_text(f"❌ Failed to update batch {batch_id}\nError: {update_response.text}")
            return

        # Second API call to add batch
        add_response = requests.get(ADD_BATCH_API.format(uid=batch_id))

        if add_response.status_code == 200:
            await message.reply_text(f"✅ Batch {batch_id} successfully added to the system!")

            # Send confirmation to all admins
            confirmation_msg = f"""
🆕 Batch Added via Command
            
🆔 **Batch ID:** `{batch_id}`
👤 **Added By:** {user.first_name}
🆔 **User ID:** `{user.id}`
"""
            if user.username:
                confirmation_msg += f"📧 **Username:** @{user.username}\n"

            for admin in AUTH_USERS:
                try:
                    await client.send_message(admin, confirmation_msg)
                except Exception as e:
                    print(f"Error sending confirmation to admin {admin}: {e}")
        else:
            await message.reply_text(f"❌ Batch {batch_id} updated but failed to add\nError: {add_response.text}")

    except Exception as e:
        await message.reply_text(f"❌ An error occurred: {str(e)}")
        print(f"Error in /add command: {e}")

# Callback query handler
@app.on_callback_query()
async def handle_callback(client: Client, callback_query: CallbackQuery):
    if not bot_enabled and callback_query.from_user.id not in AUTH_USERS:
        await callback_query.answer("❌ The bot is currently disabled. Only admins can use it.", show_alert=True)
        return

    data = callback_query.data
    user = callback_query.from_user
    
    # Add user to all_users set
    all_users.add(user.id)

    try:
        if data.startswith("show_goals_"):
            page = int(data.split("_")[2])
            keyboard = get_goals_keyboard(page)
            if keyboard:
                await callback_query.edit_message_reply_markup(keyboard)
                await callback_query.answer()
            else:
                await callback_query.answer("❌ Unable to fetch goals. Please try again.", show_alert=True)
            return

        if data == "manual_update":
            if user.id not in AUTH_USERS:
                await callback_query.answer("❌ You are not authorized to perform this action.", show_alert=True)
                return

            await callback_query.edit_message_text("🔄 Starting manual batch update...")
            success, count = await perform_batch_update()

            if success:
                await callback_query.edit_message_text(
                    f"✅ Manual Update Completed!\n\nSuccessfully updated {count} batches."
                )
            else:
                await callback_query.edit_message_text(
                    "❌ Failed to complete manual update. Please try again later."
                )
            await callback_query.answer()
            return

        if data.startswith("goals_"):
            page = int(data.split("_")[1])
            keyboard = get_goals_keyboard(page)
            if keyboard:
                await callback_query.edit_message_reply_markup(keyboard)
                await callback_query.answer()
            else:
                await callback_query.answer("❌ Unable to fetch goals. Please try again.", show_alert=True)
            return

        if data.startswith("goal_"):
            parts = data.split("_")
            goal_uid = parts[1]
            offset = int(parts[2])

            keyboard, batches = get_batches_keyboard(goal_uid, offset)
            if not keyboard or not batches:
                await callback_query.answer("❌ Koi batches nahi mile. Kripya kuch samay baad try karein.", show_alert=True)
                return

            await callback_query.edit_message_text(
                "👇 Neeche diye gaye batches mein se koi ek select karein:",
                reply_markup=keyboard
            )
            await callback_query.answer()
            return

        if data.startswith("batch_"):
            batch_uid = data.split("_")[1]
            batch = batch_cache.get(batch_uid)

            if not batch:
                await callback_query.answer("❌ Batch details not available. Please select again.", show_alert=True)
                return

            caption = format_batch_info(batch, user)

            buttons = [
                [InlineKeyboardButton("📥 Request to Add", callback_data=f"req_{batch_uid}")]
            ]

            if user.id in AUTH_USERS:
                buttons.append([InlineKeyboardButton("➕ Add Batch", callback_data=f"add_{batch_uid}")])

            request_button = InlineKeyboardMarkup(buttons)

            try:
                await callback_query.message.reply_photo(
                    photo=batch["cover_photo"],
                    caption=caption,
                    reply_markup=request_button
                )
            except Exception as e:
                print(f"Error sending photo: {e}")
                await callback_query.message.reply_text(
                    caption,
                    reply_markup=request_button
                )

            await callback_query.answer()
            return

        if data.startswith("req_"):
            batch_uid = data.split("_")[1]

            # Check request limit
            if not can_make_request(user.id):
                await callback_query.answer("❌ Aap 1 din mein maximum 5 batches hi request kar sakte hain. Kal fir try karein.", show_alert=True)
                return

            increment_request_count(user.id)

            batch = batch_cache.get(batch_uid)

            if batch:
                caption = format_batch_info(batch, user)
                buttons = [
                    [InlineKeyboardButton("📋 Copy UID", callback_data=f"copy_{batch_uid}")],
                    [InlineKeyboardButton("➕ Add Batch", callback_data=f"add_{batch_uid}")]
                ]
                copy_button = InlineKeyboardMarkup(buttons)

                for admin in AUTH_USERS:
                    try:
                        if batch.get("cover_photo"):
                            await client.send_photo(
                                admin,
                                photo=batch["cover_photo"],
                                caption=caption,
                                reply_markup=copy_button
                            )
                        else:
                            await client.send_message(
                                admin,
                                caption,
                                reply_markup=copy_button
                            )
                    except Exception as e:
                        print(f"Error sending to admin {admin}: {e}")
            else:
                simple_caption = f"""
🆕 New Batch Request
                
🆔 **Batch UID:** `{batch_uid}`
👤 **Requested By:** {user.first_name}
🆔 **User ID:** `{user.id}`
"""
                if user.username:
                    simple_caption += f"📧 **Username:** @{user.username}\n"

                buttons = [
                    [InlineKeyboardButton("📋 Copy UID", callback_data=f"copy_{batch_uid}")],
                    [InlineKeyboardButton("➕ Add Batch", callback_data=f"add_{batch_uid}")]
                ]
                copy_button = InlineKeyboardMarkup(buttons)

                for admin in AUTH_USERS:
                    try:
                        await client.send_message(
                            admin,
                            simple_caption,
                            reply_markup=copy_button
                        )
                    except Exception as e:
                        print(f"Error sending to admin {admin}: {e}")

            await callback_query.answer("✅ Request bhej di gayi hai. Admin jald hi aapko add kar denge.", show_alert=True)
            return

        if data.startswith("add_"):
            if user.id not in AUTH_USERS:
                await callback_query.answer("❌ You are not authorized to perform this action.", show_alert=True)
                return

            batch_uid = data.split("_")[1]
            await callback_query.answer("🔄 Adding batch to system...", show_alert=False)

            success = await add_batch_to_system(batch_uid, user)
            if success:
                await callback_query.message.reply_text(f"✅ Batch {batch_uid} successfully added to the system!")
            else:
                await callback_query.message.reply_text(f"❌ Failed to add batch {batch_uid}. Please try again.")

            return

        if data.startswith("copy_"):
            batch_uid = data.split("_")[1]
            await callback_query.answer(f"UID copied: {batch_uid}", show_alert=True)
            return

    except Exception as e:
        print(f"Error in callback handler: {e}")
        await callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)

async def main():
    await app.start()
    print("Bot started...")
    # Start auto_update_task only once and keep it running
    asyncio.create_task(auto_update_task())
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())