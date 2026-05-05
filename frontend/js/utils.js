// Shared Utility Functions
const DriveUtils = {
    getDriveDirectLink: function(url) {
        if (!url) return 'https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=800';
        
        // Handle direct Google Drive links
        if (url.includes('drive.google.com')) {
            const match = url.match(/\/d\/([a-zA-Z0-9_-]+)/) || url.match(/[?&]id=([a-zA-Z0-9_-]+)/);
            if (match && match[1]) {
                return `https://lh3.googleusercontent.com/d/${match[1]}`;
            }
        }
        
        // Return original url if not matched
        return url;
    }
};

window.DriveUtils = DriveUtils;
