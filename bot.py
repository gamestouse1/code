import os
import re
import json
import time
import requests
from urllib.parse import urlparse, parse_qs
from telebot import TeleBot, types
from bs4 import BeautifulSoup

# Security best practice: Use environment variables for sensitive tokens
# If running locally, replace these with your actual tokens
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7246965764:AAGnAahu5MUf5YTSjg4xPls13WHSqV90BBg')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@shop_xpert')
AMAZON_AFFILIATE_TAG = os.environ.get('AMAZON_AFFILIATE_TAG', 'getfreedeal77-21')
FLIPKART_AFFILIATE_ID = os.environ.get('FLIPKART_AFFILIATE_ID', 'YOUR_FLIPKART_AFFILIATE_ID')

bot = TeleBot(BOT_TOKEN)

# Store temporary post data and edit states
post_data = {}
edit_states = {}

# Define edit fields
EDIT_FIELDS = ['title', 'offer_price', 'mrp', 'discount_amount', 'discount_percent', 'promo_code']


def extract_amazon_asin(url):
    """Extract ASIN from Amazon URL"""
    parsed_url = urlparse(url)
    if 'amazon' not in parsed_url.netloc:
        return None

    # Try to find ASIN in URL path
    path_parts = parsed_url.path.split('/')
    for i, part in enumerate(path_parts):
        if part == 'dp' and i + 1 < len(path_parts):
            return path_parts[i + 1]

    # Try to find ASIN in query parameters
    query_params = parse_qs(parsed_url.query)
    if 'ASIN' in query_params:
        return query_params['ASIN'][0]

    return None


def extract_flipkart_id(url):
    """Extract product ID from Flipkart URL"""
    parsed_url = urlparse(url)
    if 'flipkart' not in parsed_url.netloc:
        return None

    # Common pattern for Flipkart product URLs
    match = re.search(r'/p/([a-zA-Z0-9]+)', parsed_url.path)
    if match:
        return match.group(1)

    return None


def convert_to_affiliate_link(url):
    """Convert regular URL to affiliate URL"""
    if 'amazon' in url:
        asin = extract_amazon_asin(url)
        if asin:
            return f"https://www.amazon.in/dp/{asin}?tag={AMAZON_AFFILIATE_TAG}"
    elif 'flipkart' in url:
        prod_id = extract_flipkart_id(url)
        if prod_id and FLIPKART_AFFILIATE_ID != 'YOUR_FLIPKART_AFFILIATE_ID':
            return f"https://www.flipkart.com/p/{prod_id}?affid={FLIPKART_AFFILIATE_ID}"

    # Return original URL if we couldn't convert it
    return url


def truncate_title(title, max_length=70):
    """Truncate title and add ellipsis if too long"""
    if len(title) <= max_length:
        return title
    return title[:max_length].rstrip() + "..."


def fetch_product_data(url):
    """Fetch product details from the URL"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raise exception for HTTP errors
        soup = BeautifulSoup(response.text, 'html.parser')

        # Initialize with default values
        data = {
            'title': 'Product Title Not Found',
            'image_url': None,
            'offer_price': 'N/A',
            'mrp': 'N/A',
            'discount_amount': 'N/A',
            'discount_percent': 'N/A',
            'affiliate_link': convert_to_affiliate_link(url),
            'promo_code': ''  # Initialize empty promo code
        }

        if 'amazon' in url:
            # Amazon specific parsing
            title_elem = soup.select_one('#productTitle')
            if title_elem:
                data['title'] = truncate_title(title_elem.text.strip())

            # Amazon sometimes uses different image selectors
            img_elem = soup.select_one('#landingImage, #imgBlkFront')
            if img_elem and 'src' in img_elem.attrs:
                data['image_url'] = img_elem['src']
            elif img_elem and 'data-a-dynamic-image' in img_elem.attrs:
                # Extract from JSON string if using data attribute
                img_json = json.loads(img_elem['data-a-dynamic-image'])
                if img_json:
                    data['image_url'] = list(img_json.keys())[0]

            # Try multiple price selectors as Amazon changes them frequently
            price_elem = soup.select_one('.a-price .a-offscreen, .a-price-whole')
            if price_elem:
                price_text = price_elem.text.strip()
                if not price_text.startswith('₹'):
                    price_text = '₹' + price_text
                data['offer_price'] = price_text.replace(',', '')

            mrp_elem = soup.select_one('.a-text-price .a-offscreen, .a-text-price span[aria-hidden="true"]')
            if mrp_elem:
                data['mrp'] = mrp_elem.text.strip()

                # Calculate discount if both prices are available
                if data['offer_price'] != 'N/A' and data['mrp'] != 'N/A':
                    try:
                        offer = float(data['offer_price'].replace('₹', '').replace(',', ''))
                        mrp = float(data['mrp'].replace('₹', '').replace(',', ''))

                        if mrp > offer:
                            discount_amount = mrp - offer
                            discount_percent = (discount_amount / mrp) * 100
                            data['discount_amount'] = f"₹{discount_amount:.0f}"
                            data['discount_percent'] = f"{discount_percent:.0f}% off"
                    except ValueError:
                        print(f"Error converting prices: offer={data['offer_price']}, mrp={data['mrp']}")

        elif 'flipkart' in url:
            # Flipkart specific parsing
            title_elem = soup.select_one('.B_NuCI')
            if title_elem:
                data['title'] = truncate_title(title_elem.text.strip())

            # Flipkart image selectors
            img_elem = soup.select_one('._396cs4, .CXW8mj img')
            if img_elem and 'src' in img_elem.attrs:
                data['image_url'] = img_elem['src']

            price_elem = soup.select_one('._30jeq3._16Jk6d')
            if price_elem:
                data['offer_price'] = price_elem.text.strip()

            mrp_elem = soup.select_one('._3I9_wc._2p6lqe')
            if mrp_elem:
                data['mrp'] = mrp_elem.text.strip()

            discount_elem = soup.select_one('._3Ay6Sb._31Dcoz')
            if discount_elem:
                discount_text = discount_elem.text.strip()
                if discount_text.startswith('-'):
                    discount_text = discount_text[1:]
                data['discount_percent'] = discount_text

            # Attempt to find promo codes - this can be site-specific
            promo_elem = soup.select_one('._16eBzU span')
            if promo_elem and promo_elem.text.strip():
                data['promo_code'] = promo_elem.text.strip()

            if data['offer_price'] != 'N/A' and data['mrp'] != 'N/A':
                try:
                    offer = float(data['offer_price'].replace('₹', '').replace(',', ''))
                    mrp = float(data['mrp'].replace('₹', '').replace(',', ''))

                    if mrp > offer:
                        discount_amount = mrp - offer
                        data['discount_amount'] = f"₹{discount_amount:.0f}"

                        if data['discount_percent'] == 'N/A':
                            discount_percent = (discount_amount / mrp) * 100
                            data['discount_percent'] = f"{discount_percent:.0f}% off"
                except ValueError:
                    print(f"Error converting prices: offer={data['offer_price']}, mrp={data['mrp']}")

        return data

    except requests.RequestException as e:
        print(f"Network error fetching product data: {e}")
        return None
    except Exception as e:
        print(f"Error fetching product data: {e}")
        return None


def create_post_text(product_data):
    """Create formatted post text from product data"""
    post_text = f"*{product_data['title']}*\n\n"
    post_text += f"*Offer Price:* {product_data['offer_price']}\n"
    post_text += f"*MRP:* {product_data['mrp']}\n"

    # Format the Save section
    if product_data['discount_amount'] != 'N/A' and product_data['discount_percent'] != 'N/A':
        post_text += f"*Save* {product_data['discount_amount']} ({product_data['discount_percent']})\n"
    elif product_data['discount_percent'] != 'N/A':
        post_text += f"*Save* ({product_data['discount_percent']})\n"
    elif product_data['discount_amount'] != 'N/A':
        post_text += f"_{'Save '}{product_data['discount_amount']}_ 🔥\n"

    # Add promo code if available
    if product_data.get('promo_code'):
        post_text += f"\n🎟️ Apply Coupon!: {product_data['promo_code']}"

    return post_text


@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
                 "Welcome to Affiliate Link Generator Bot!\n\n"
                 "Send me an Amazon or Flipkart product URL, and I'll convert it to an affiliate link "
                 "and generate a formatted post for your channel 2.")


@bot.message_handler(regexp='(https?://)?(www\.)?(amazon|flipkart)\.(in|com)/.*')
def handle_product_url(message):
    url = message.text.strip()
    processing_msg = bot.reply_to(message, "Processing your product link...")

    product_data = fetch_product_data(url)
    if not product_data:
        bot.edit_message_text("Sorry, I couldn't fetch the product details. Please check if the URL is valid.",
                              chat_id=message.chat.id,
                              message_id=processing_msg.message_id)
        return

    post_data[message.chat.id] = product_data

    # Create keyboard with edit button
    markup = types.InlineKeyboardMarkup()
    buy_button = types.InlineKeyboardButton("🛒 Buy Now", url=product_data['affiliate_link'])
    edit_button = types.InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")
    send_button = types.InlineKeyboardButton("Send to Channel", callback_data="send_to_channel")
    markup.add(buy_button)
    markup.add(edit_button)
    markup.add(send_button)

    post_text = create_post_text(product_data)

    try:
        if product_data['image_url']:
            bot.send_photo(
                message.chat.id,
                photo=product_data['image_url'],
                caption=post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.send_message(
                message.chat.id,
                post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )

        bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
    except Exception as e:
        bot.edit_message_text(
            f"Error creating preview: {str(e)}. Try again or try a different link.",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )


@bot.callback_query_handler(func=lambda call: call.data == "edit_caption")
def edit_caption_menu(call):
    user_id = call.message.chat.id
    if user_id not in post_data:
        bot.answer_callback_query(call.id, "Session expired. Please send the product link again.")
        return

    markup = types.InlineKeyboardMarkup()
    for field in EDIT_FIELDS:
        button_text = field.replace('_', ' ').title()
        markup.add(types.InlineKeyboardButton(f"Edit {button_text}", callback_data=f"edit_{field}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_preview"))

    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_") and not call.data == "edit_caption")
def handle_edit_field(call):
    user_id = call.message.chat.id
    field = call.data.replace("edit_", "")

    if field not in EDIT_FIELDS:
        return

    edit_states[user_id] = field
    current_value = post_data[user_id].get(field, '')

    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        user_id,
        f"Please enter new {field.replace('_', ' ')}.\nCurrent value: {current_value}",
        reply_markup=types.ForceReply()
    )
    bot.register_next_step_handler(msg, process_edit_input)


def process_edit_input(message):
    user_id = message.chat.id
    if user_id not in edit_states or user_id not in post_data:
        bot.reply_to(message, "Session expired. Please start over.")
        return

    field = edit_states[user_id]
    post_data[user_id][field] = message.text.strip()

    # Update the preview message
    post_text = create_post_text(post_data[user_id])
    markup = types.InlineKeyboardMarkup()
    buy_button = types.InlineKeyboardButton("🛒 Buy Now", url=post_data[user_id]['affiliate_link'])
    edit_button = types.InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")
    send_button = types.InlineKeyboardButton("Send to Channel", callback_data="send_to_channel")
    markup.add(buy_button)
    markup.add(edit_button)
    markup.add(send_button)

    bot.send_message(
        user_id,
        f"✅ {field.replace('_', ' ').title()} updated successfully!\n\nUpdated Preview:",
        parse_mode='Markdown'
    )

    try:
        if post_data[user_id]['image_url']:
            bot.send_photo(
                user_id,
                photo=post_data[user_id]['image_url'],
                caption=post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.send_message(
                user_id,
                post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
    except Exception as e:
        bot.send_message(user_id, f"Error sending preview: {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data == "back_to_preview")
def back_to_preview(call):
    user_id = call.message.chat.id
    if user_id not in post_data:
        bot.answer_callback_query(call.id, "Session expired. Please send the product link again.")
        return

    markup = types.InlineKeyboardMarkup()
    buy_button = types.InlineKeyboardButton("🛒 Buy Now", url=post_data[user_id]['affiliate_link'])
    edit_button = types.InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")
    send_button = types.InlineKeyboardButton("Send to Channel", callback_data="send_to_channel")
    markup.add(buy_button)
    markup.add(edit_button)
    markup.add(send_button)

    post_text = create_post_text(post_data[user_id])

    try:
        # Check if the message is a photo or text message
        if hasattr(call.message, 'photo') and call.message.photo:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.edit_message_text(
                text=post_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        bot.answer_callback_query(call.id, "Preview updated!")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Error updating preview: {str(e)[:20]}")


@bot.callback_query_handler(func=lambda call: call.data == "send_to_channel")
def send_to_channel(call):
    user_id = call.message.chat.id
    if user_id not in post_data:
        bot.answer_callback_query(call.id, "Session expired. Please send the product link again.")
        return

    product_data = post_data[user_id]
    post_text = create_post_text(product_data)

    # Create keyboard with buy button including basket icon
    markup = types.InlineKeyboardMarkup()
    buy_button = types.InlineKeyboardButton("🛒 Buy Now", url=product_data['affiliate_link'])
    markup.add(buy_button)

    try:
        # Send to channel with image if available
        if product_data['image_url']:
            bot.send_photo(
                CHANNEL_ID,
                photo=product_data['image_url'],
                caption=post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.send_message(
                CHANNEL_ID,
                post_text,
                parse_mode='Markdown',
                reply_markup=markup
            )

        bot.answer_callback_query(call.id, "Successfully posted to channel!")
        bot.send_message(user_id, "✅ Post has been sent to the channel successfully!")

    except Exception as e:
        error_message = str(e)
        bot.answer_callback_query(call.id, "Failed to post to channel.")
        bot.send_message(
            user_id,
            f"❌ Failed to post to channel: {error_message}\n\nPlease check if the bot has admin rights in the channel and the channel ID is correct."
        )


# Single catch-all handler for invalid URLs
@bot.message_handler(func=lambda message: True)
def handle_invalid_message(message):
    if re.search('https?://', message.text):
        bot.reply_to(message, "This doesn't look like an Amazon or Flipkart URL. Please send a valid product link.")
    else:
        bot.reply_to(message, "Please send an Amazon or Flipkart product URL to generate an affiliate link and post.")


def main():
    max_retries = 10
    retry_count = 0

    while retry_count < max_retries:
        try:
            print("Bot started...")
            # Poll Telegram for updates
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
            break  # Exit loop if polling ends normally

        except requests.exceptions.ReadTimeout:
            print("Timeout error, reconnecting...")
            time.sleep(3)

        except requests.exceptions.ConnectionError:
            print("Connection error, waiting before retry...")
            time.sleep(10)

        except Exception as e:
            print(f"Bot stopped due to error: {e}")
            retry_count += 1
            wait_time = min(30, 5 * retry_count)  # Progressive backoff
            print(f"Retrying in {wait_time} seconds... (Attempt {retry_count}/{max_retries})")
            time.sleep(wait_time)

    if retry_count >= max_retries:
        print("Max retries reached. Bot is shutting down.")


if __name__ == '__main__':
    main()
