import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

# Ensure secrets are always loaded from the project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)

# Generate a 256-bit encryption key (Base64 encoded) if not found in .env
CRYPTO_KEY_B64 = os.environ.get("CRYPTO_KEY")
if not CRYPTO_KEY_B64:
    # Fallback to dev key only if .env was not found
    print("⚠️ WARNING: CRYPTO_KEY not found in environment, using development default!")
    CRYPTO_KEY_B64 = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode('utf-8')

CRYPTO_KEY = base64.b64decode(CRYPTO_KEY_B64)

def encrypt_data(plain_text):
    """
    Encrypts a string using AES-256-GCM.
    Returns: A base64 encoded string containing the nonce and ciphertext.
    """
    if not plain_text:
        return None
        
    aesgcm = AESGCM(CRYPTO_KEY)
    nonce = os.urandom(12)  # Recommended nonce length for GCM
    
    # Encrypt the plain text string (converted to bytes)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode('utf-8'), None)
    
    # Bundle nonce and ciphertext together and base64 encode for storage
    return base64.b64encode(nonce + ciphertext).decode('utf-8')

def decrypt_data(cipher_text_b64):
    """
    Decrypts a base64 encoded AES-256-GCM ciphertext.
    Includes sanity checks for base64 format to avoid noise on legacy data.
    """
    if not cipher_text_b64 or not isinstance(cipher_text_b64, str):
        return cipher_text_b64
        
    try:
        # Sanity check: Base64 strings should have length multiple of 4 (with padding)
        # or at least look like base64. 
        if len(cipher_text_b64) % 4 != 0 and len(cipher_text_b64) < 16:
            # Likely legacy plain text
            return cipher_text_b64

        combined_data = base64.b64decode(cipher_text_b64)
        if len(combined_data) < 12: # At least nonce length
             return cipher_text_b64

        nonce = combined_data[:12]
        ciphertext = combined_data[12:]
        
        aesgcm = AESGCM(CRYPTO_KEY)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        # Silently return the original text if decryption fails (likely legacy data)
        # log internally only if needed
        return cipher_text_b64

# Initial production key verification complete. Key is now managed via environment variables.
